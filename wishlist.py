#!/usr/bin/env python3
import os
import time
import re
import requests
from urllib.parse import urlencode
from lxml import etree
from dataclasses import dataclass
from typing import List, Optional, Set

# ====== CONFIG via environment ======
SPOTWEB_BASE_URL = os.environ["SPOTWEB_BASE_URL"].rstrip("/")
SPOTWEB_APIKEY   = os.environ["SPOTWEB_APIKEY"]
SAB_BASE_URL     = os.environ["SAB_BASE_URL"].rstrip("/")
SAB_APIKEY       = os.environ["SAB_APIKEY"]

WISHLIST_FILE    = os.environ.get("WISHLIST_FILE", "/data/wishlist.txt")
INTERVAL_SECONDS = int(os.environ.get("INTERVAL_SECONDS", "900"))
SPOTWEB_CAT      = os.environ.get("SPOTWEB_CAT", "7020")   # Ebook
SAB_CATEGORY     = os.environ.get("SAB_CATEGORY", "books")


# ============================================================
# 1) Wishlist format: [schrijver] [schrijver] ... - "titel"
# ============================================================

STOPWORDS: Set[str] = {
    "de","het","een","van","en","der","den","te","in","op","voor","met","aan","bij","uit",
    "the","a","an","of","and","to","in","on","for","with",
}

@dataclass(frozen=True)
class WishlistEntry:
    authors: List[str]  # tokens (minstens 1)
    title: str          # string uit quotes
    raw: str            # originele regel


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"[^a-z0-9à-ÿ\s-]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokens(s: str) -> List[str]:
    parts = _norm(s).replace("-", " ").split()
    return [w for w in parts if w and w not in STOPWORDS and len(w) > 1]


def parse_wishlist_line(line: str) -> Optional[WishlistEntry]:
    """
    Verwacht:
        Achternaam Achternaam ... - "Titel"

    Voorbeeld:
        Horst Fjell - "De schreeuw"
    """
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None

    m = re.match(r'^(.*?)\s*-\s*"(.+)"\s*$', raw)
    if not m:
        return None

    author_part = m.group(1).strip()
    title_part  = m.group(2).strip()

    authors = _tokens(author_part)
    title_tokens = _tokens(title_part)

    if not authors or not title_tokens:
        return None

    return WishlistEntry(authors=authors, title=title_part, raw=raw)


def candidate_matches(entry: WishlistEntry, candidate_title: str) -> bool:
    """
    Jouw regel:
    - minstens 1 schrijver-token moet voorkomen
    - én de titel moet terugkomen in de gevonden woorden

    Concreet:
    - author_ok: minimaal 1 author-token in candidate
    - title_ok:
        - als titel >= 3 tokens: minimaal 2 titel-tokens matchen
        - anders: minimaal 1 titel-token matchen
    """
    cand = set(_tokens(candidate_title))

    author_ok = any(a in cand for a in entry.authors)
    if not author_ok:
        return False

    title_tokens = _tokens(entry.title)
    if len(title_tokens) >= 3:
        title_ok = sum(1 for t in title_tokens if t in cand) >= 2
    else:
        title_ok = any(t in cand for t in title_tokens)

    return author_ok and title_ok


# ============================================================
# 2) wishlist.txt IO (zelfde als jij had)
# ============================================================

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
    Zelfde functie als jij had: meerdere varianten maken.
    (Je kunt 'm blijven gebruiken zoals je deed.)
    """
    variants: list[str] = []

    t = text.strip()
    t_norm = t.replace("–", "-").replace("—", "-")
    variants.append(t)
    if t_norm != t:
        variants.append(t_norm)

    parts = [p.strip() for p in t_norm.split("-") if p.strip()]
    if len(parts) == 2:
        left, right = parts
        variants.extend([left, right, f"{right} {left}", f"{left} {right}"])

    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", t_norm, flags=re.UNICODE)
    if words:
        variants.append(" ".join(words))
        variants.append(words[-1])
    if len(words) >= 3:
        variants.append(" ".join(words[-3:]))

    seen = set()
    out: list[str] = []
    for v in variants:
        v = v.strip()
        key = v.lower()
        if v and key not in seen:
            out.append(v)
            seen.add(key)

    return out


# ============================================================
# 3) JOUW BESTAANDE FUNCTIES (signatures gelijk, bodies niet)
#    -> Plak jouw werkende implementaties hier terug.
# ============================================================





def spotweb_search_first_nzb_url(query: str) -> str | None:
    """
    (Plak hier jouw bestaande werkende body.)

    Tip voor integratie van matching:
    - parse entry = parse_wishlist_line(query)  (kan None zijn)
    - als entry is None: val terug op 'oude gedrag' (bijv. eerste hit)
    - als entry bestaat: gebruik candidate_matches(entry, candidate_title)
      om resultaten te filteren voordat je een url returned.
    """
    """
    Vraagt Spotweb Newznab API om resultaten en pakt de eerste enclosure URL (NZB).
    Tolerant XML parsen via lxml (recover=True), omdat Spotweb XML soms niet strikt valide is.
    """
    parser = etree.XMLParser(recover=True)
    entry = parse_wishlist_line(query)
    candidate_title = ""
    print("DEBUG entry:", entry)
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
            title_el = item.find("title")
            if title_el is None:
                continue

            candidate_title = title_el.text or ""
            
            print("DEBUG candidate_title:", repr(candidate_title))
            print("DEBUG author tokens:", entry.authors if entry else None)
            print("DEBUG title tokens:", _tokens(entry.title) if entry else None)
            print("DEBUG matches?:", candidate_matches(entry, candidate_title) if entry else None)

            # >>> DIT IS DE NIEUWE CHECK <<<
            if entry and not candidate_matches(entry, candidate_title):
                continue
            
            enc = item.find("enclosure")
            if enc is not None and "url" in enc.attrib:
                print(f"Match gevonden via zoekterm: {q}")
                return enc.attrib["url"]

    print("DEBUG ABOUT TO RETURN:", candidate_title)
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
    


# ============================================================
# 4) MAIN (zelfde flow, maar met parsing-validatie)
# ============================================================

def main() -> None:
    print("Wishlist container gestart")

    while True:
        wishlist_lines = read_wishlist(WISHLIST_FILE)

        if not wishlist_lines:
            print("Wishlist leeg, wachten...")
            time.sleep(INTERVAL_SECONDS)
            continue

        remaining: list[str] = []

        for line in wishlist_lines:
            # Validatie van jouw nieuwe format
            entry = parse_wishlist_line(line)
            
            if entry is None:
                print(f"Ongeldige wishlist-regel (verwacht: auteurs - \"titel\"): {line}")
                remaining.append(line)
                continue

            try:
                # Signature blijft: query is een string (de originele regel)
                nzb_url = spotweb_search_first_nzb_url(entry.raw)

                if not nzb_url:
                    print(f"Niet gevonden: {entry.raw}")
                    remaining.append(entry.raw)
                    continue

                ok = sab_addurl(nzb_url, nzbname=entry.raw)
                if ok:
                    print(f"Toegevoegd: {entry.raw}")
                else:
                    print(f"Kon niet toevoegen: {entry.raw}")
                    remaining.append(entry.raw)

            except Exception as e:
                print(f"Fout bij '{entry.raw}': {e}")
                remaining.append(entry.raw)

        if remaining != wishlist_lines:
            write_wishlist(WISHLIST_FILE, remaining)
            print(f"Wishlist bijgewerkt ({len(remaining)} over)")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()






