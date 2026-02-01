#!/usr/bin/env python3
"""
Worker proces voor Wishlist applicatie.
Leest pending items uit database, zoekt in Spotweb, en voegt toe aan SABnzbd.
"""
import os
import time
import re
import requests
from urllib.parse import urlencode
from lxml import etree
from typing import List, Optional, Set

import database as db

# Config via environment
SPOTWEB_BASE_URL = os.environ["SPOTWEB_BASE_URL"].rstrip("/")
SPOTWEB_APIKEY = os.environ["SPOTWEB_APIKEY"]
SAB_BASE_URL = os.environ["SAB_BASE_URL"].rstrip("/")
SAB_APIKEY = os.environ["SAB_APIKEY"]

INTERVAL_SECONDS = int(os.environ.get("INTERVAL_SECONDS", "900"))  # 15 min
SPOTWEB_CAT = os.environ.get("SPOTWEB_CAT", "7020")  # Ebook
SAB_CATEGORY = os.environ.get("SAB_CATEGORY", "books")

# Stopwoorden voor matching
STOPWORDS: Set[str] = {
    "de", "het", "een", "van", "en", "der", "den", "te", "in", "op", "voor", "met", "aan", "bij", "uit",
    "the", "a", "an", "of", "and", "to", "in", "on", "for", "with",
}


def _norm(s: str) -> str:
    """Normaliseer string voor matching."""
    s = (s or "").lower()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"[^a-z0-9à-ÿ\s-]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokens(s: str) -> List[str]:
    """Maak tokens van string (zonder stopwords)."""
    parts = _norm(s).replace("-", " ").split()
    return [w for w in parts if w and w not in STOPWORDS and len(w) > 1]


def candidate_matches(author: str, title: str, candidate_title: str) -> bool:
    """
    Check of candidate title match is met author en title.

    Logica:
    - Minimaal 1 author token moet voorkomen in candidate
    - Voor titel:
        - Als titel >= 3 tokens: minimaal 2 titel tokens moeten matchen
        - Anders: minimaal 1 titel token moet matchen
    """
    author_tokens = _tokens(author)
    title_tokens = _tokens(title)
    candidate_tokens = set(_tokens(candidate_title))

    # Check author
    author_ok = any(a in candidate_tokens for a in author_tokens)
    if not author_ok:
        return False

    # Check title
    if len(title_tokens) >= 3:
        title_ok = sum(1 for t in title_tokens if t in candidate_tokens) >= 2
    else:
        title_ok = any(t in candidate_tokens for t in title_tokens)

    return author_ok and title_ok


def search_variants(author: str, title: str) -> List[str]:
    """
    Maak zoek varianten voor betere Spotweb matches.

    Returns: Lijst van zoekstrings om te proberen
    """
    variants = []

    # Basis: auteur titel
    variants.append(f"{author} {title}")
    variants.append(f"{title} {author}")

    # Alleen titel
    variants.append(title)

    # Alleen auteur
    variants.append(author)

    # Laatste woord van titel (vaak kernwoord)
    title_words = title.split()
    if len(title_words) > 1:
        variants.append(title_words[-1])

    # Laatste woord auteur + titel
    author_words = author.split()
    if len(author_words) > 1:
        variants.append(f"{author_words[-1]} {title}")

    # Uniek houden
    seen = set()
    unique_variants = []
    for v in variants:
        v_lower = v.lower().strip()
        if v_lower and v_lower not in seen:
            unique_variants.append(v)
            seen.add(v_lower)

    return unique_variants


def spotweb_search(author: str, title: str) -> Optional[str]:
    """
    Zoek in Spotweb naar item.

    Returns: NZB URL als gevonden, anders None
    """
    parser = etree.XMLParser(recover=True)
    search_attempts = 0
    total_results = 0

    for query in search_variants(author, title):
        search_attempts += 1
        print(f"   Zoekpoging {search_attempts}: '{query}'")

        params = {
            "apikey": SPOTWEB_APIKEY,
            "t": "search",
            "extended": "1",
            "q": query,
            "cat": SPOTWEB_CAT,
            "limit": "25",
        }

        url = f"{SPOTWEB_BASE_URL}/api?{urlencode(params)}"

        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()

            root = etree.fromstring(r.content, parser)
            channel = root.find("channel")

            if channel is None:
                print(f"   → Geen resultaten")
                continue

            results = channel.findall("item")
            result_count = len(results)
            total_results += result_count
            print(f"   → {result_count} resultaten gevonden")

            # Check alle resultaten
            for item in results:
                title_el = item.find("title")
                if title_el is None:
                    continue

                candidate_title = title_el.text or ""

                # Check of het een match is
                if candidate_matches(author, title, candidate_title):
                    enc = item.find("enclosure")
                    if enc is not None and "url" in enc.attrib:
                        nzb_url = enc.attrib["url"]
                        print(f"   ✓ MATCH: {candidate_title[:80]}")
                        return nzb_url

        except requests.RequestException as e:
            print(f"   ✗ Spotweb fout: {e}")
            continue
        except Exception as e:
            print(f"   ✗ Parse fout: {e}")
            continue

    print(f"   ✗ Niet gevonden ({search_attempts} zoekopdrachten, {total_results} resultaten)")
    return None


def sab_addurl(nzb_url: str, nzbname: str) -> bool:
    """
    Voeg NZB URL toe aan SABnzbd.

    Returns: True als succesvol, anders False
    """
    params = {
        "mode": "addurl",
        "name": nzb_url,
        "nzbname": nzbname,
        "apikey": SAB_APIKEY,
        "output": "json",
    }

    if SAB_CATEGORY:
        params["cat"] = SAB_CATEGORY

    url = f"{SAB_BASE_URL}/api?{urlencode(params)}"

    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()

        data = r.json()
        success = bool(data.get("status")) or bool(data.get("nzo_ids"))

        if not success:
            print(f"   ✗ SABnzbd response: {data}")
            db.add_log(None, "error", f"SABnzbd weigerde NZB: {data.get('error', data)}")

        return success

    except Exception as e:
        db.add_log(None, "error", f"SABnzbd fout: {e}")
        print(f"   ✗ SABnzbd exception: {e}")
        return False


def process_item(item: dict) -> None:
    """
    Verwerk een enkel wishlist item.

    Zoekt in Spotweb en voegt toe aan SABnzbd indien gevonden.
    """
    item_id = item['id']
    author = item['author']
    title = item['title']

    print(f"\n🔍 Zoeken: {author} - \"{title}\"")
    db.add_log(item_id, "info", "Zoeken gestart")

    # Update status naar searching
    db.update_wishlist_status(item_id, "searching")

    try:
        # Zoek in Spotweb
        nzb_url = spotweb_search(author, title)

        if not nzb_url:
            print(f"   ✗ Niet gevonden")
            db.update_wishlist_status(
                item_id,
                "pending",
                error_message="Niet gevonden in Spotweb"
            )
            return

        print(f"   ✓ NZB gevonden")

        # Voeg toe aan SABnzbd
        nzbname = f"{author} - {title}"
        success = sab_addurl(nzb_url, nzbname)

        if success:
            print(f"   ✓ Toegevoegd aan SABnzbd")
            db.update_wishlist_status(
                item_id,
                "found",
                nzb_url=nzb_url
            )
            db.add_log(item_id, "info", "✓ Toegevoegd aan SABnzbd")

            # Optioneel: verwijder item automatisch na toevoegen
            # db.delete_wishlist_item(item_id)

        else:
            print(f"   ✗ Kon niet toevoegen aan SABnzbd")
            db.update_wishlist_status(
                item_id,
                "failed",
                nzb_url=nzb_url,
                error_message="SABnzbd toevoegen mislukt"
            )

    except Exception as e:
        print(f"   ✗ Fout: {e}")
        db.update_wishlist_status(
            item_id,
            "failed",
            error_message=str(e)
        )
        db.add_log(item_id, "error", f"Fout: {e}")


def worker_loop() -> None:
    """Main worker loop."""
    print("🔧 Worker gestart")
    print(f"   Spotweb: {SPOTWEB_BASE_URL}")
    print(f"   SABnzbd: {SAB_BASE_URL}")
    print(f"   Interval: {INTERVAL_SECONDS}s")

    while True:
        try:
            # Haal pending items op
            pending_items = db.get_wishlist_items(status='pending')

            if not pending_items:
                print(f"\n😴 Geen pending items, wachten {INTERVAL_SECONDS}s...")
            else:
                print(f"\n📋 {len(pending_items)} pending item(s) gevonden")

                # Verwerk elk item
                for item in pending_items:
                    process_item(item)

                    # Kleine pauze tussen items
                    time.sleep(2)

        except Exception as e:
            print(f"❌ Fout in worker loop: {e}")
            db.add_log(None, "error", f"Worker fout: {e}")

        # Wacht tot volgende run
        time.sleep(INTERVAL_SECONDS)


def main():
    """Main entry point."""
    # Initialiseer database
    db.init_db()

    # Start worker loop
    worker_loop()


if __name__ == "__main__":
    main()
