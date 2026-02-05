#!/usr/bin/env python3
"""
Calibre-Web integratie module.
Haalt boekenplanken op via de Calibre-Web web interface.
"""
import os
import re
import requests
from typing import List, Dict, Optional

CALIBREWEB_URL = os.environ.get("CALIBREWEB_URL", "").rstrip("/")
CALIBREWEB_USERNAME = os.environ.get("CALIBREWEB_USERNAME", "")
CALIBREWEB_PASSWORD = os.environ.get("CALIBREWEB_PASSWORD", "")

# Cache voor sessie en planken
_session: Optional[requests.Session] = None
_shelves_cache: Optional[List[Dict]] = None
_cache_time: float = 0
CACHE_TTL = 300  # 5 minuten


def is_configured() -> bool:
    """Check of Calibre-Web integratie geconfigureerd is."""
    return bool(CALIBREWEB_URL and CALIBREWEB_USERNAME and CALIBREWEB_PASSWORD)


def _get_session() -> requests.Session:
    """Login bij Calibre-Web en return sessie met cookies."""
    global _session

    if _session is not None:
        return _session

    session = requests.Session()
    login_url = f"{CALIBREWEB_URL}/login"

    try:
        # Haal login pagina op voor CSRF token
        resp = session.get(login_url, timeout=10)
        resp.raise_for_status()

        # Extract CSRF token uit login formulier
        csrf_match = re.search(
            r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']',
            resp.text
        )
        if not csrf_match:
            # Probeer alternatief patroon
            csrf_match = re.search(
                r'id=["\']csrf_token["\']\s+[^>]*value=["\']([^"\']+)["\']',
                resp.text
            )

        # Login POST
        login_data = {
            "username": CALIBREWEB_USERNAME,
            "password": CALIBREWEB_PASSWORD,
            "submit": "",
            "next": "/",
            "remember_me": "on",
        }

        if csrf_match:
            login_data["csrf_token"] = csrf_match.group(1)

        resp = session.post(login_url, data=login_data, timeout=10, allow_redirects=True)
        resp.raise_for_status()

        # Check of login gelukt is (redirect naar / of bevat geen login form)
        if "/login" in resp.url and "login" in resp.text.lower():
            raise ConnectionError("Calibre-Web login mislukt - controleer credentials")

        _session = session
        return session

    except requests.RequestException as e:
        raise ConnectionError(f"Calibre-Web niet bereikbaar: {e}")


def _invalidate_session():
    """Reset sessie zodat opnieuw ingelogd wordt."""
    global _session
    _session = None


def fetch_shelves() -> List[Dict]:
    """
    Haal openbare boekenplanken op uit Calibre-Web.

    Returns: Lijst van dicts met 'id', 'name', 'count'
    """
    import time
    global _shelves_cache, _cache_time

    # Return cache als nog geldig
    if _shelves_cache is not None and (time.time() - _cache_time) < CACHE_TTL:
        return _shelves_cache

    if not is_configured():
        return []

    try:
        session = _get_session()
        resp = session.get(f"{CALIBREWEB_URL}/", timeout=10)
        resp.raise_for_status()
    except ConnectionError:
        _invalidate_session()
        # Probeer opnieuw met verse sessie
        session = _get_session()
        resp = session.get(f"{CALIBREWEB_URL}/", timeout=10)
        resp.raise_for_status()

    shelves = _parse_shelves(resp.text)

    _shelves_cache = shelves
    _cache_time = time.time()

    return shelves


def _parse_shelves(html: str) -> List[Dict]:
    """
    Parse boekenplanken uit Calibre-Web sidebar HTML.

    Zoekt naar links met /shelf/<id> patroon in de navigatie.
    """
    shelves = []

    # Zoek alle shelf links: <a href="/shelf/123">...Naam (Openbaar)...<span class="badge">5</span></a>
    # Stap 1: vind alle shelf <a> blokken
    link_pattern = r'href="[^"]*?/shelf/(\d+)"[^>]*>(.*?)</a>'
    for match in re.finditer(link_pattern, html, re.DOTALL):
        shelf_id = match.group(1)
        inner = match.group(2)

        # Stap 2: verwijder HTML tags om de naam te krijgen
        name = re.sub(r'<[^>]+>', ' ', inner).strip()
        # Verwijder extra whitespace
        name = re.sub(r'\s+', ' ', name).strip()

        if not name:
            continue

        # Stap 3: extract count uit badge span
        count_match = re.search(r'class="[^"]*badge[^"]*"[^>]*>\s*(\d+)\s*<', inner)
        count = int(count_match.group(1)) if count_match else 0

        # Verwijder count uit naam als het erin zit
        if count:
            name = re.sub(r'\s*\d+\s*$', '', name).strip()

        shelves.append({
            "id": int(shelf_id),
            "name": name,
            "count": count,
        })

    # Verwijder duplicaten (kan voorkomen door meerdere links naar zelfde shelf)
    seen = set()
    unique = []
    for s in shelves:
        if s["id"] not in seen:
            seen.add(s["id"])
            unique.append(s)

    return unique


def clear_cache():
    """Wis de planken-cache."""
    global _shelves_cache, _cache_time
    _shelves_cache = None
    _cache_time = 0


def _get_shelf_id(shelf_name: str) -> Optional[int]:
    """Zoek shelf_id op basis van naam. Ondersteunt fuzzy matching."""
    shelves = fetch_shelves()

    # Exacte match eerst
    for shelf in shelves:
        if shelf["name"] == shelf_name:
            return shelf["id"]

    # Fuzzy match: case-insensitive, "Kobo GJ" matcht "Kobo GJ (Openbaar)"
    shelf_lower = shelf_name.lower().strip()
    for shelf in shelves:
        if shelf["name"].lower().startswith(shelf_lower):
            print(f"      Shelf fuzzy match: '{shelf_name}' → '{shelf['name']}'")
            return shelf["id"]

    # Nog losser: check of alle woorden voorkomen
    shelf_words = shelf_lower.split()
    for shelf in shelves:
        name_lower = shelf["name"].lower()
        if all(w in name_lower for w in shelf_words):
            print(f"      Shelf fuzzy match: '{shelf_name}' → '{shelf['name']}'")
            return shelf["id"]

    return None


def search_book(author: str, title: str) -> Optional[int]:
    """
    Zoek een boek in Calibre-Web via de OPDS feed.

    Returns: book_id als gevonden, anders None
    """
    if not is_configured():
        return None

    from lxml import etree

    query = f"{author} {title}"
    print(f"      OPDS zoekquery: '{query}'")

    try:
        # OPDS gebruikt Basic Auth, niet session cookies
        resp = requests.get(
            f"{CALIBREWEB_URL}/opds/search",
            params={"query": query},
            auth=(CALIBREWEB_USERNAME, CALIBREWEB_PASSWORD),
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"      OPDS zoeken mislukt: {e}")
        return None

    # Parse Atom XML
    try:
        root = etree.fromstring(resp.content)
    except Exception as e:
        print(f"      OPDS XML parse fout: {e}")
        return None

    # Atom namespace
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)

    # Probeer ook zonder namespace (sommige Calibre-Web versies)
    if not entries:
        entries = root.findall("entry")

    if not entries:
        print(f"      Geen OPDS resultaten voor '{query}'")
        return None

    print(f"      {len(entries)} OPDS resultaat(en) gevonden")

    author_lower = author.lower()
    title_lower = title.lower()
    author_parts = [p.strip() for p in author_lower.split() if len(p.strip()) > 2]
    title_parts = [p.strip() for p in title_lower.split() if len(p.strip()) > 2]

    for entry in entries:
        entry_title_el = entry.find("atom:title", ns)
        entry_title = entry_title_el.text if entry_title_el is not None else ""
        entry_author_el = entry.find("atom:author/atom:name", ns)
        entry_author = entry_author_el.text if entry_author_el is not None else ""

        # Zoek book ID uit links (cover of download URL)
        book_id = None
        for link in entry.findall("atom:link", ns):
            href = link.get("href", "")
            book_match = re.search(r'/opds/(?:cover|download)/(\d+)', href)
            if not book_match:
                book_match = re.search(r'/book/(\d+)', href)
            if book_match:
                book_id = int(book_match.group(1))
                break

        if book_id is None:
            continue

        # Match check
        combined = f"{entry_title} {entry_author}".lower()
        author_ok = any(part in combined for part in author_parts) if author_parts else True
        title_ok = any(part in combined for part in title_parts) if title_parts else True

        if author_ok and title_ok:
            print(f"      ✓ Match: book_id={book_id}, '{entry_title}' door {entry_author}")
            return book_id
        else:
            reasons = []
            if not author_ok:
                reasons.append(f"auteur [{', '.join(author_parts)}]")
            if not title_ok:
                reasons.append(f"titel [{', '.join(title_parts)}]")
            print(f"      ✗ Geen match: book_id={book_id}, '{entry_title}' door {entry_author} - {', '.join(reasons)} niet gevonden")

    print(f"      Geen matching boek in {len(entries)} resultaat(en)")
    return None


def add_book_to_shelf(shelf_name: str, book_id: int) -> bool:
    """
    Voeg een boek toe aan een boekenplank in Calibre-Web.

    Returns: True als succesvol
    """
    shelf_id = _get_shelf_id(shelf_name)
    if shelf_id is None:
        print(f"      ✗ Boekenplank '{shelf_name}' niet gevonden in Calibre-Web")
        print(f"      Beschikbare planken: {[s['name'] for s in fetch_shelves()]}")
        return False

    print(f"      Plank toevoegen: shelf_id={shelf_id}, book_id={book_id}, naam='{shelf_name}'")

    session = _get_session()
    url = f"{CALIBREWEB_URL}/shelf/add/{shelf_id}/{book_id}"

    try:
        resp = session.post(url, timeout=10, allow_redirects=True)

        if resp.status_code in (200, 302):
            print(f"      ✓ Boek {book_id} toegevoegd aan plank '{shelf_name}' (status={resp.status_code})")
            return True

        print(f"      ✗ Onverwachte response: status={resp.status_code}, url={url}")
        print(f"      Response body: {resp.text[:200]}")
        return False

    except requests.RequestException as e:
        print(f"      ✗ HTTP fout bij plank toevoegen: {e}")
        _invalidate_session()
        return False
