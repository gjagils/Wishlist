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
    """Zoek shelf_id op basis van naam."""
    shelves = fetch_shelves()
    for shelf in shelves:
        if shelf["name"] == shelf_name:
            return shelf["id"]
    return None


def search_book(author: str, title: str) -> Optional[int]:
    """
    Zoek een boek in Calibre-Web op auteur en titel.

    Returns: book_id als gevonden, anders None
    """
    if not is_configured():
        return None

    session = _get_session()
    query = f"{author} {title}"

    try:
        resp = session.get(
            f"{CALIBREWEB_URL}/search",
            params={"query": query},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException:
        _invalidate_session()
        return None

    # Parse zoekresultaten: zoek book links /book/<id>
    book_pattern = r'href="[^"]*?/book/(\d+)"'
    book_ids = re.findall(book_pattern, resp.text)

    if not book_ids:
        return None

    # Check elk resultaat of auteur+titel matchen
    author_lower = author.lower()
    title_lower = title.lower()

    for book_id in dict.fromkeys(book_ids):  # unieke IDs, volgorde behouden
        try:
            resp = session.get(f"{CALIBREWEB_URL}/book/{book_id}", timeout=10)
            resp.raise_for_status()
            page_lower = resp.text.lower()

            # Check of auteur en titel voorkomen op de boekpagina
            author_parts = [p.strip() for p in author_lower.split() if len(p.strip()) > 2]
            title_parts = [p.strip() for p in title_lower.split() if len(p.strip()) > 2]

            author_ok = any(part in page_lower for part in author_parts) if author_parts else True
            title_ok = any(part in page_lower for part in title_parts) if title_parts else True

            if author_ok and title_ok:
                return int(book_id)

        except requests.RequestException:
            continue

    return None


def add_book_to_shelf(shelf_name: str, book_id: int) -> bool:
    """
    Voeg een boek toe aan een boekenplank in Calibre-Web.

    Returns: True als succesvol
    """
    shelf_id = _get_shelf_id(shelf_name)
    if shelf_id is None:
        print(f"   ✗ Boekenplank '{shelf_name}' niet gevonden in Calibre-Web")
        return False

    session = _get_session()

    try:
        resp = session.post(
            f"{CALIBREWEB_URL}/shelf/add/{shelf_id}/{book_id}",
            timeout=10,
            allow_redirects=True,
        )
        # Calibre-Web retourneert redirect of JSON bij succes
        if resp.status_code in (200, 302):
            return True

        print(f"   ✗ Shelf add response: {resp.status_code}")
        return False

    except requests.RequestException as e:
        print(f"   ✗ Shelf add fout: {e}")
        _invalidate_session()
        return False
