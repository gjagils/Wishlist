#!/usr/bin/env python3
"""
Calibre-Web integratie module.
Haalt boekenplanken op via de Calibre-Web web interface.
"""
import os
import re
import unicodedata
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


def _opds_search(query: str) -> Optional[list]:
    """
    Voer een OPDS zoekopdracht uit en return entries of None.
    Gebruikt Basic Auth (OPDS accepteert geen session cookies).
    """
    from lxml import etree

    opds_url = f"{CALIBREWEB_URL}/opds/search"

    try:
        resp = requests.get(
            opds_url,
            params={"query": query},
            auth=(CALIBREWEB_USERNAME, CALIBREWEB_PASSWORD),
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"      OPDS request mislukt: {e}")
        return None

    # Check of we XML terugkrijgen
    content_type = resp.headers.get("content-type", "")
    if "html" in content_type:
        print(f"      OPDS gaf HTML terug i.p.v. XML (auth probleem?)")
        return None

    try:
        root = etree.fromstring(resp.content)
    except Exception as e:
        print(f"      OPDS XML parse fout: {e}")
        return None

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    if not entries:
        entries = root.findall("entry")

    return entries if entries else None


def search_book(author: str, title: str) -> Optional[int]:
    """
    Zoek een boek in Calibre-Web via de OPDS feed.
    Probeert meerdere zoekstrategieën: titel, auteur+titel, auteur.

    Returns: book_id als gevonden, anders None
    """
    if not is_configured():
        return None

    # Probeer meerdere queries - Calibre-Web OPDS zoekt soms alleen op één veld
    queries = [title, f"{author} {title}", author]
    # Verwijder duplicaten met behoud van volgorde
    seen = set()
    unique_queries = []
    for q in queries:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            unique_queries.append(q)

    entries = None
    used_query = None
    for query in unique_queries:
        print(f"      OPDS zoekquery: '{query}'")
        entries = _opds_search(query)
        if entries:
            used_query = query
            print(f"      {len(entries)} OPDS resultaat(en) gevonden")
            break
        print(f"      Geen resultaten")

    if not entries:
        print(f"      Geen OPDS resultaten na {len(unique_queries)} pogingen")
        return None

    # Match entries tegen auteur en titel
    # Strip accenten voor vergelijking (björg → bjorg, aegisdóttir → aegisdottir)
    def _normalize(text: str) -> str:
        text = unicodedata.normalize("NFD", text.lower())
        return "".join(c for c in text if unicodedata.category(c) != "Mn")

    author_norm = _normalize(author)
    title_norm = _normalize(title)
    author_parts = [p.strip() for p in author_norm.split() if len(p.strip()) > 2]
    title_parts = [p.strip() for p in title_norm.split() if len(p.strip()) > 2]

    ns = {"atom": "http://www.w3.org/2005/Atom"}

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

        # Match check (accent-insensitive)
        combined = _normalize(f"{entry_title} {entry_author}")
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


def _get_csrf_token(session: requests.Session, page_url: str) -> Optional[str]:
    """Haal CSRF token op uit een pagina."""
    try:
        resp = session.get(page_url, timeout=10)
        resp.raise_for_status()

        # Patroon 1: <input name="csrf_token" ... value="xxx">
        csrf_match = re.search(
            r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)["\']',
            resp.text
        )
        # Patroon 2: <input value="xxx" ... name="csrf_token">
        if not csrf_match:
            csrf_match = re.search(
                r'value=["\']([^"\']+)["\'][^>]*name=["\']csrf_token["\']',
                resp.text
            )
        # Patroon 3: <meta name="csrf-token" content="xxx">
        if not csrf_match:
            csrf_match = re.search(
                r'<meta\s+[^>]*name=["\']csrf-token["\'][^>]*content=["\']([^"\']+)["\']',
                resp.text
            )
        # Patroon 4: csrf_token in JavaScript variable
        if not csrf_match:
            csrf_match = re.search(
                r'csrf_token\s*[=:]\s*["\']([^"\']+)["\']',
                resp.text
            )

        if csrf_match:
            return csrf_match.group(1)

        # Fallback: check csrf_token cookie
        if "csrf_token" in session.cookies:
            return session.cookies["csrf_token"]

        print(f"      Geen CSRF token gevonden op {page_url} (pagina={len(resp.text)} bytes, url={resp.url})")
        return None
    except requests.RequestException as e:
        print(f"      CSRF ophalen mislukt: {e}")
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

    # Haal CSRF token op van de boekpagina
    book_page = f"{CALIBREWEB_URL}/book/{book_id}"
    csrf_token = _get_csrf_token(session, book_page)
    if not csrf_token:
        # Fallback: probeer CSRF van hoofdpagina
        csrf_token = _get_csrf_token(session, f"{CALIBREWEB_URL}/")

    if not csrf_token:
        print(f"      ⚠ Geen CSRF token - probeer toch POST")
    else:
        print(f"      CSRF token verkregen ({csrf_token[:20]}...)")

    # Probeer meerdere methodes om het boek toe te voegen
    attempts = [
        ("header+form", {"X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf_token or ""}, {"csrf_token": csrf_token or ""}),
        ("form-only", {"X-Requested-With": "XMLHttpRequest"}, {"csrf_token": csrf_token or ""}),
        ("header-only", {"X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf_token or ""}, None),
        ("plain-post", {}, None),
    ]

    try:
        for desc, headers, data in attempts:
            resp = session.post(url, headers=headers, data=data, timeout=10, allow_redirects=True)
            if resp.status_code in (200, 204, 302):
                print(f"      ✓ Boek {book_id} toegevoegd aan plank '{shelf_name}' (methode={desc}, status={resp.status_code})")
                return True
            print(f"      Poging '{desc}': status={resp.status_code}")

        print(f"      ✗ Alle pogingen mislukt voor {url}")
        print(f"      Session cookies: {list(session.cookies.keys())}")
        print(f"      Laatste response: {resp.text[:300]}")
        return False

    except requests.RequestException as e:
        print(f"      ✗ HTTP fout bij plank toevoegen: {e}")
        _invalidate_session()
        return False
