#!/usr/bin/env python3
"""
Worker proces voor Wishlist applicatie.
Leest pending items uit database, zoekt in Spotweb, en voegt toe aan SABnzbd.
"""
import os
import time
import re
import requests
from datetime import datetime
from urllib.parse import urlencode
from lxml import etree
from typing import List, Optional, Set

import database as db
import calibreweb
import email_sender

# Config via environment
SPOTWEB_BASE_URL = os.environ["SPOTWEB_BASE_URL"].rstrip("/")
SPOTWEB_APIKEY = os.environ["SPOTWEB_APIKEY"]
SAB_BASE_URL = os.environ["SAB_BASE_URL"].rstrip("/")
SAB_APIKEY = os.environ["SAB_APIKEY"]

INTERVAL_SECONDS = int(os.environ.get("INTERVAL_SECONDS", "900"))  # 15 min
IMPORT_CHECK_SECONDS = int(os.environ.get("IMPORT_CHECK_SECONDS", "120"))  # 2 min
IMPORT_TIMEOUT_HOURS = float(os.environ.get("IMPORT_TIMEOUT_HOURS", "6"))
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

    variants.append(f"{author} {title}")
    variants.append(f"{title} {author}")
    variants.append(title)
    variants.append(author)

    title_words = title.split()
    if len(title_words) > 1:
        variants.append(title_words[-1])

    author_words = author.split()
    if len(author_words) > 1:
        variants.append(f"{author_words[-1]} {title}")

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

    for query in search_variants(author, title):
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
                continue

            results = channel.findall("item")

            for item in results:
                title_el = item.find("title")
                if title_el is None:
                    continue

                candidate_title = title_el.text or ""

                if candidate_matches(author, title, candidate_title):
                    enc = item.find("enclosure")
                    if enc is not None and "url" in enc.attrib:
                        return enc.attrib["url"]

        except Exception:
            continue

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
            db.add_log(None, "error", f"SABnzbd weigerde NZB: {data.get('error', data)}")

        return success

    except Exception as e:
        db.add_log(None, "error", f"SABnzbd fout: {e}")
        return False


def process_item(item: dict) -> None:
    """
    Verwerk een enkel wishlist item.

    Zoekt in Spotweb en voegt toe aan SABnzbd indien gevonden.
    """
    item_id = item['id']
    author = item['author']
    title = item['title']

    db.add_log(item_id, "info", "Zoeken gestart")
    db.update_wishlist_status(item_id, "searching")

    try:
        nzb_url = spotweb_search(author, title)

        if not nzb_url:
            db.update_wishlist_status(
                item_id,
                "pending",
                error_message="Niet gevonden in Spotweb"
            )
            return

        nzbname = f"{author} - {title}"
        success = sab_addurl(nzb_url, nzbname)

        if success:
            if calibreweb.is_configured():
                db.update_wishlist_status(item_id, "found", nzb_url=nzb_url)
                db.add_log(item_id, "info", "✓ Toegevoegd aan SABnzbd, wachten op Calibre-Web import")
            else:
                # Geen Calibre-Web integratie: niets om op te wachten of te bevestigen
                db.update_wishlist_status(item_id, "done", nzb_url=nzb_url)
                db.add_log(item_id, "info", "✓ Toegevoegd aan SABnzbd")

            # E-mail notificatie
            try:
                email_sender.notify_item_found(item)
            except Exception as e:
                db.add_log(item_id, "warning", f"E-mail notificatie mislukt: {e}")

        else:
            db.update_wishlist_status(
                item_id,
                "failed",
                nzb_url=nzb_url,
                error_message="SABnzbd toevoegen mislukt"
            )

    except Exception as e:
        db.update_wishlist_status(
            item_id,
            "failed",
            error_message=str(e)
        )
        db.add_log(item_id, "error", f"Fout: {e}")


def finalize_import(item: dict, book_id: int) -> None:
    """
    Verwerk een bevestigde match in Calibre-Web ('imported').

    Zonder boekenplank is het item meteen 'done'. Met boekenplank wordt
    geprobeerd te shelven: gelukt → 'shelved', mislukt → 'shelf_failed'
    (blijft zichtbaar als foutstatus, net als 'failed' en 'stuck').
    """
    item_id = item['id']
    shelf_name = item.get('shelf_name')
    nzb_url = item.get('nzb_url')

    db.update_wishlist_status(item_id, "imported", nzb_url=nzb_url)
    db.add_log(item_id, "info", f"✓ Geïmporteerd in Calibre-Web (book_id={book_id})")

    if not shelf_name:
        db.update_wishlist_status(item_id, "done", nzb_url=nzb_url)
        return

    success = calibreweb.add_book_to_shelf(shelf_name, book_id)

    if success:
        db.update_wishlist_status(item_id, "shelved", nzb_url=nzb_url)
        db.add_log(item_id, "info", f"✓ Op boekenplank gezet: {shelf_name} (book_id={book_id})")

        try:
            email_sender.notify_item_shelved(item)
        except Exception as e:
            db.add_log(item_id, "warning", f"E-mail notificatie mislukt: {e}")
    else:
        db.update_wishlist_status(
            item_id,
            "shelf_failed",
            nzb_url=nzb_url,
            error_message=f"Plank '{shelf_name}' toevoegen mislukt"
        )
        db.add_log(item_id, "warning",
                   f"Boek geïmporteerd (book_id={book_id}) maar plank toevoegen mislukt: {shelf_name}")


def match_recent_import(item: dict) -> Optional[int]:
    """
    Fallback voor als search_book() geen match vindt: kijk of het boek
    tussen de meest recent toegevoegde boeken in Calibre-Web zit met een
    titel/auteur die lijkt op (maar niet noodzakelijk exact overeenkomt met)
    dit item — bv. omdat Calibre-Web de metadata net iets anders heeft
    geparsed bij de import.

    Corrigeert bij een match ook meteen de titel/auteur in Calibre-Web naar
    de canonieke waarden uit de wishlist.

    Returns: book_id als er een aannemelijke recente match is, anders None
    """
    item_id = item['id']
    author = item['author']
    title = item['title']

    recent_books = calibreweb.get_recent_books(limit=10)

    for book in recent_books:
        candidate = f"{book['title']} {book['author']}"
        if not candidate_matches(author, title, candidate):
            continue

        book_id = book['book_id']

        if book['title'].strip().lower() != title.strip().lower():
            if not calibreweb.update_book_title(book_id, title):
                db.add_log(item_id, "warning",
                           f"Metadata-titel bijwerken mislukt (book_id={book_id}), "
                           f"controleer Edit-rechten van de Calibre-Web integratie-account")
        if book['author'].strip().lower() != author.strip().lower():
            if not calibreweb.update_book_author(book_id, author):
                db.add_log(item_id, "warning",
                           f"Metadata-auteur bijwerken mislukt (book_id={book_id}), "
                           f"controleer Edit-rechten van de Calibre-Web integratie-account")

        return book_id

    return None


def check_found_items() -> None:
    """
    Check items met status 'found': zoek in Calibre-Web en rond af als
    het boek gevonden wordt (zie finalize_import).

    Items die langer dan IMPORT_TIMEOUT_HOURS niet gematcht kunnen worden
    (bv. omdat de import in Calibre-Web nooit gebeurt of titel/auteur niet
    matchen) worden op 'stuck' gezet zodat ze niet stil voor altijd blijven
    hangen op 'found'.
    """
    if not calibreweb.is_configured():
        return

    found_items = db.get_wishlist_items(status='found')
    if not found_items:
        return

    for item in found_items:
        item_id = item['id']
        author = item['author']
        title = item['title']

        try:
            book_id = calibreweb.search_book(author, title)

            if not book_id:
                book_id = match_recent_import(item)
                if book_id:
                    db.add_log(item_id, "info",
                               f"✓ Match gevonden via 'recent toegevoegd' (book_id={book_id}), "
                               f"metadata gecontroleerd/gecorrigeerd")

            if not book_id:
                found_since = item.get('last_search')
                elapsed_hours = None
                if found_since:
                    try:
                        elapsed_hours = (datetime.now() - datetime.fromisoformat(found_since)).total_seconds() / 3600
                    except ValueError:
                        elapsed_hours = None

                if elapsed_hours is not None and elapsed_hours >= IMPORT_TIMEOUT_HOURS:
                    db.update_wishlist_status(
                        item_id,
                        "stuck",
                        nzb_url=item.get('nzb_url'),
                        error_message=f"Niet gevonden in Calibre-Web na {IMPORT_TIMEOUT_HOURS:.0f} uur wachten"
                    )
                    db.add_log(item_id, "warning",
                               f"Vastgelopen: boek na {elapsed_hours:.1f} uur nog niet gematcht in Calibre-Web "
                               f"(auteur='{author}', titel='{title}') — controleer of het boek is geïmporteerd "
                               f"en of titel/auteur overeenkomen")

                continue

            finalize_import(item, book_id)

        except Exception as e:
            db.add_log(item_id, "error", f"Calibre-Web fout: {e}")

        time.sleep(2)


CALIBRE_CHECK_SECONDS = int(os.environ.get("CALIBRE_CHECK_SECONDS", "86400"))  # 24 uur


def check_existing_in_calibre() -> None:
    """
    Check of pending items al in Calibre-Web bestaan.
    Voorkomt dubbele downloads — als een boek al in de bibliotheek staat,
    wordt het direct afgerond via finalize_import.
    """
    if not calibreweb.is_configured():
        return

    pending = db.get_wishlist_items(status='pending')
    if not pending:
        return

    for item in pending:
        item_id = item['id']
        author = item['author']
        title = item['title']

        try:
            book_id = calibreweb.search_book(author, title)
            if not book_id:
                continue

            db.add_log(item_id, "info", f"✓ Boek bestond al in Calibre-Web (book_id={book_id})")
            finalize_import(item, book_id)

        except Exception as e:
            db.add_log(item_id, "error", f"Calibre-Web check fout: {e}")

        time.sleep(2)


def worker_loop() -> None:
    """Main worker loop."""
    print("Worker gestart")

    last_search_time = 0
    last_calibre_check = 0

    while True:
        try:
            now = time.time()

            # Dagelijkse check: bestaan pending items al in Calibre-Web?
            if now - last_calibre_check >= CALIBRE_CHECK_SECONDS:
                check_existing_in_calibre()
                last_calibre_check = time.time()

            if now - last_search_time >= INTERVAL_SECONDS:
                pending_items = db.get_wishlist_items(status='pending')

                if pending_items:
                    for item in pending_items:
                        process_item(item)
                        time.sleep(2)

                last_search_time = time.time()

            check_found_items()

        except Exception as e:
            db.add_log(None, "error", f"Worker fout: {e}")

        time.sleep(IMPORT_CHECK_SECONDS)


def main():
    """Main entry point."""
    db.init_db()
    worker_loop()


if __name__ == "__main__":
    main()
