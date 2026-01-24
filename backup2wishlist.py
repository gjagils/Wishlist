#!/usr/bin/env python3
import os
import time
import re
import requests
from urllib.parse import urlencode
from lxml import etree

# ====== CONFIG via environment ======
SPOTWEB_BASE_URL = os.environ["SPOTWEB_BASE_URL"].rstrip("/")
SPOTWEB_APIKEY   = os.environ["SPOTWEB_APIKEY"]
SAB_BASE_URL     = os.environ["SAB_BASE_URL"].rstrip("/")
SAB_APIKEY       = os.environ["SAB_APIKEY"]

WISHLIST_FILE    = os.environ.get("WISHLIST_FILE", "/data/wishlist.txt")
INTERVAL_SECONDS = int(os.environ.get("INTERVAL_SECONDS", "900"))
SPOTWEB_CAT      = os.environ.get("SPOTWEB_CAT", "7020")   # Ebook
SAB_CATEGORY     = os.environ.get("SAB_CATEGORY", "books")


def read_wishlist(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]


def write_wishlist(path: str, items: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(items) + ("\n" if items else ""))


def search_variants(text: str) -> list[str]:
    """
    Maak meerdere zoekvarianten omdat Spotweb API vaak strenger zoekt
    dan de webinterface (volgorde titel/auteur, streepjes, leestekens).
    """
    variants: list[str] = []

    t = text.strip()

    # Normaliseer streepjes
    t_norm = t.replace("–", "-").replace("—", "-")
    variants.append(t)
    if t_norm != t:
        variants.append(t_norm)

    # Als er precies 2 delen zijn gesplitst door '-', probeer combinaties
    parts = [p.strip() for p in t_norm.split("-") if p.strip()]
    if len(parts) == 2:
        left, right = parts
        variants.extend([
            left,                  # bv "De camino"
            right,                 # bv "Anya Niewierra"
            f"{right} {left}",     # auteur titel
            f"{left} {right}",     # titel auteur
        ])

    # Alleen woorden (geen leestekens)
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", t_norm, flags=re.UNICODE)
    if words:
        variants.append(" ".join(words))      # alles als woorden
        variants.append(words[-1])            # laatste woord (bv "camino")
    if len(words) >= 3:
        variants.append(" ".join(words[-3:])) # laatste 3 woorden

    # Uniek houden
    seen = set()
    out: list[str] = []
    for v in variants:
        v = v.strip()
        key = v.lower()
        if v and key not in seen:
            out.append(v)
            seen.add(key)

    return out


def spotweb_search_first_nzb_url(query: str) -> str | None:
    """
    Vraagt Spotweb Newznab API om resultaten en pakt de eerste enclosure URL (NZB).
    Tolerant XML parsen via lxml (recover=True), omdat Spotweb XML soms niet strikt valide is.
    """
    parser = etree.XMLParser(recover=True)

    for q in search_variants(query):
        params = {
            "apikey": SPOTWEB_APIKEY,
            "t": "search",
            "extended": "1",
            "q": q,
            "cat": SPOTWEB_CAT,
            "limit": "25",
        }
        url = f"{SPOTWEB_BASE_URL}/api?{urlencode(params)}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()

        root = etree.fromstring(r.content, parser)
        channel = root.find("channel")
        if channel is None:
            continue

        for item in channel.findall("item"):
            enc = item.find("enclosure")
            if enc is not None and "url" in enc.attrib:
                print(f"Match gevonden via zoekterm: {q}")
                return enc.attrib["url"]

    return None


def sab_addurl(nzb_url: str, nzbname: str) -> bool:
    """
    Voegt NZB URL toe aan SABnzbd via API (addurl).
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
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    data = r.json()
    return bool(data.get("status")) or bool(data.get("nzo_ids"))


def main() -> None:
    print("Wishlist container gestart (Spotweb -> SABnzbd)")

    while True:
        wishlist = read_wishlist(WISHLIST_FILE)

        if not wishlist:
            print("Wishlist leeg, wachten...")
            time.sleep(INTERVAL_SECONDS)
            continue

        remaining: list[str] = []

        for book in wishlist:
            try:
                nzb_url = spotweb_search_first_nzb_url(book)

                if not nzb_url:
                    print(f"Niet gevonden: {book}")
                    remaining.append(book)
                    continue

                ok = sab_addurl(nzb_url, nzbname=book)
                if ok:
                    print(f"Toegevoegd aan SAB: {book}")
                    # SAB regelt download + mail (zoals jij hebt ingesteld)
                else:
                    print(f"SAB kon niet toevoegen: {book}")
                    remaining.append(book)

            except Exception as e:
                print(f"Fout bij '{book}': {e}")
                remaining.append(book)

        if remaining != wishlist:
            write_wishlist(WISHLIST_FILE, remaining)
            print(f"Wishlist bijgewerkt ({len(remaining)} over)")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
