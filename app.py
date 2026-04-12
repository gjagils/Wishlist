#!/usr/bin/env python3
"""
Flask web applicatie voor Wishlist beheer.
Biedt web UI en REST API met sessie-authenticatie via Calibre-Web.
"""
import json
import os
import re
import threading
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, url_for, send_from_directory, Response
from werkzeug.security import check_password_hash, generate_password_hash

import database as db
import calibreweb

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Legacy single-user credentials (fallback als Calibre-Web niet geconfigureerd is)
LEGACY_USERNAME = os.environ.get('WEB_USERNAME', 'admin')
LEGACY_PASSWORD_HASH = generate_password_hash(os.environ.get('WEB_PASSWORD', 'wishlist'))


def get_current_user():
    """Haal huidige ingelogde user op uit sessie."""
    username = session.get('username')
    if not username:
        return None
    return db.get_user(username)


def requires_auth(f):
    """Decorator voor endpoints die authenticatie vereisen."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('username'):
            return f(*args, **kwargs)

        # Check of het een API call is
        is_api = (request.path.startswith('/api/') or
                  request.headers.get('Accept') == 'application/json' or
                  request.headers.get('X-Requested-With') == 'XMLHttpRequest')

        if is_api:
            return jsonify({'error': 'Authenticatie vereist'}), 401

        return redirect(url_for('login'))
    return decorated


def requires_admin(f):
    """Decorator voor admin-only endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or user['role'] != 'admin':
            return jsonify({'error': 'Admin rechten vereist'}), 403
        return f(*args, **kwargs)
    return decorated


# ===== AUTH ROUTES =====

@app.route('/autologin', methods=['GET'])
def autologin():
    """
    Auto-login via gedeeld geheim of HMAC-signed URL.

    Twee modes:
    1. Shared key: /autologin?user=naam&key=<AUTOLOGIN_KEY>
       → Voor Calibre-Web template: {{ current_user.name }} als user
    2. HMAC token: /autologin?user=naam&token=<hmac>&ts=<timestamp>
       → Voor admin-gegenereerde links (30 dagen geldig)
    """
    import hmac
    import hashlib

    username = request.args.get('user', '')
    if not username:
        return redirect(url_for('login'))

    authenticated = False

    # Mode 1: Shared key (voor Calibre-Web template links)
    key = request.args.get('key', '')
    autologin_key = os.environ.get('AUTOLOGIN_KEY', app.config['SECRET_KEY'])
    if key and hmac.compare_digest(key, autologin_key):
        authenticated = True

    # Mode 2: HMAC token (voor admin-gegenereerde links)
    token = request.args.get('token', '')
    ts = request.args.get('ts', '')
    if not authenticated and token:
        secret = app.config['SECRET_KEY']
        expected = hmac.new(
            secret.encode(), f"{username}:{ts}".encode(), hashlib.sha256
        ).hexdigest()[:32]

        if hmac.compare_digest(token, expected):
            # Check timestamp (max 30 dagen)
            if ts:
                try:
                    from datetime import datetime
                    age = (datetime.now() - datetime.fromisoformat(ts)).days
                    authenticated = age <= 30
                except Exception:
                    authenticated = True
            else:
                authenticated = True

    if not authenticated:
        return redirect(url_for('login'))

    # Auto-registratie
    user = db.get_user(username)
    if not user:
        db.create_user(username=username)
        user = db.get_user(username)

    db.update_user_login(username)
    session['username'] = username
    session.permanent = True

    return redirect('/')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login pagina en authenticatie."""
    if request.method == 'GET':
        if session.get('username'):
            return redirect('/')
        return send_from_directory('static', 'login.html')

    # POST: authenticeer
    data = request.get_json() if request.is_json else None
    if data:
        username = data.get('username', '').strip()
        password = data.get('password', '')
    else:
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

    if not username or not password:
        return jsonify({'error': 'Gebruikersnaam en wachtwoord zijn verplicht'}), 400

    # Probeer authenticatie via Calibre-Web
    authenticated = False
    auth_method = "none"
    if calibreweb.is_configured():
        authenticated = calibreweb.authenticate_user(username, password)
        auth_method = "calibreweb"
    else:
        # Fallback: legacy single-user auth
        authenticated = (username == LEGACY_USERNAME and
                        check_password_hash(LEGACY_PASSWORD_HASH, password))
        auth_method = "legacy"

    print(f"[LOGIN] user='{username}', method={auth_method}, "
          f"calibreweb_configured={calibreweb.is_configured()}, "
          f"calibreweb_url='{calibreweb.CALIBREWEB_URL}', "
          f"authenticated={authenticated}")

    if not authenticated:
        return jsonify({'error': 'Ongeldige gebruikersnaam of wachtwoord'}), 401

    # Auto-registratie: maak user aan als die nog niet bestaat
    user = db.get_user(username)
    if not user:
        db.create_user(username=username)
        user = db.get_user(username)

    db.update_user_login(username)

    session['username'] = username
    session.permanent = True

    return jsonify({'message': 'Ingelogd', 'user': {
        'username': user['username'],
        'role': user['role'],
    }})


@app.route('/logout')
def logout():
    """Uitloggen."""
    session.clear()
    return redirect(url_for('login'))


# ===== WEB UI =====

@app.route('/')
@requires_auth
def index():
    """Hoofdpagina met web interface."""
    response = send_from_directory('static', 'index.html')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/admin')
@requires_auth
@requires_admin
def admin_page():
    """Admin pagina voor gebruikersbeheer."""
    response = send_from_directory('static', 'admin.html')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/portal')
def portal():
    """Portaal pagina met links naar alle apps (geen auth vereist)."""
    response = send_from_directory('static', 'portal.html')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/static/<path:path>')
def serve_static(path):
    """Serveer statische bestanden."""
    response = send_from_directory('static', path)
    response.headers['Cache-Control'] = 'public, max-age=3600, must-revalidate'
    return response


# ===== API: ME =====

@app.route('/api/me', methods=['GET'])
@requires_auth
def api_me():
    """Haal huidige user info op."""
    user = get_current_user()
    return jsonify({
        'username': user['username'],
        'role': user['role'],
        'email': user['email'],
        'allowed_shelves': user['allowed_shelves'],
    })


# ===== API: WISHLIST =====

@app.route('/api/wishlist', methods=['GET'])
@requires_auth
def api_get_wishlist():
    """Haal wishlist items op. Admin ziet alles, user ziet eigen items."""
    user = get_current_user()
    status = request.args.get('status')

    if user['role'] == 'admin':
        items = db.get_wishlist_items(status=status)
    else:
        items = db.get_wishlist_items(status=status, user_id=user['id'])

    # Stats over zichtbare items
    if user['role'] == 'admin':
        all_items = db.get_wishlist_items()
    else:
        all_items = db.get_wishlist_items(user_id=user['id'])

    stats = {
        'total': len(all_items),
        'pending': len([i for i in all_items if i['status'] == 'pending']),
        'searching': len([i for i in all_items if i['status'] == 'searching']),
        'found': len([i for i in all_items if i['status'] == 'found']),
        'importing': len([i for i in all_items if i['status'] == 'importing']),
        'shelved': len([i for i in all_items if i['status'] == 'shelved']),
        'failed': len([i for i in all_items if i['status'] == 'failed']),
    }

    return jsonify({
        'items': items,
        'stats': stats
    })


@app.route('/api/wishlist/<int:item_id>', methods=['GET'])
@requires_auth
def api_get_wishlist_item(item_id: int):
    """Haal enkel wishlist item op."""
    user = get_current_user()
    item = db.get_wishlist_item(item_id)
    if not item:
        return jsonify({'error': 'Item niet gevonden'}), 404

    # Gewone user mag alleen eigen items zien
    if user['role'] != 'admin' and item.get('user_id') != user['id']:
        return jsonify({'error': 'Geen toegang'}), 403

    logs = db.get_logs(wishlist_id=item_id)
    item['logs'] = logs

    return jsonify(item)


@app.route('/api/wishlist', methods=['POST'])
@requires_auth
def api_add_wishlist():
    """Voeg nieuw item toe aan wishlist."""
    user = get_current_user()
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Geen data ontvangen'}), 400

    author = data.get('author', '').strip()
    title = data.get('title', '').strip()

    if not author or not title:
        return jsonify({'error': 'Auteur en titel zijn verplicht'}), 400

    shelf_name = data.get('shelf_name')

    # Valideer plank-toegang voor gewone users
    if user['role'] != 'admin' and shelf_name:
        if not user['allowed_shelves'] or shelf_name not in user['allowed_shelves']:
            return jsonify({'error': 'Je hebt geen toegang tot deze boekenplank'}), 403

    # Gewone user zonder planken mag geen items toevoegen
    if user['role'] != 'admin' and not user['allowed_shelves']:
        return jsonify({'error': 'Je hebt nog geen boekenplank toegewezen gekregen. Vraag de beheerder.'}), 403

    try:
        item_id = db.add_wishlist_item(
            author=author,
            title=title,
            added_via=data.get('added_via', 'web'),
            shelf_name=shelf_name,
            user_id=user['id']
        )

        item = db.get_wishlist_item(item_id)
        return jsonify({
            'message': 'Item toegevoegd',
            'item': item
        }), 201

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Server fout: {str(e)}'}), 500


@app.route('/api/wishlist/<int:item_id>', methods=['PUT'])
@requires_auth
def api_update_wishlist(item_id: int):
    """Bewerk item (auteur, titel, plank)."""
    user = get_current_user()
    item = db.get_wishlist_item(item_id)

    if not item:
        return jsonify({'error': 'Item niet gevonden'}), 404

    if user['role'] != 'admin' and item.get('user_id') != user['id']:
        return jsonify({'error': 'Geen toegang'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Geen data ontvangen'}), 400

    author = data.get('author', '').strip()
    title = data.get('title', '').strip()
    shelf_name = data.get('shelf_name')

    if not author or not title:
        return jsonify({'error': 'Auteur en titel zijn verplicht'}), 400

    # Valideer plank-toegang voor gewone users
    if user['role'] != 'admin' and shelf_name:
        if not user['allowed_shelves'] or shelf_name not in user['allowed_shelves']:
            return jsonify({'error': 'Je hebt geen toegang tot deze boekenplank'}), 403

    no_cover = data.get('no_cover', False)

    try:
        db.update_wishlist_item(item_id, author=author, title=title, shelf_name=shelf_name)

        # Cover cache: skip of opnieuw zoeken
        if no_cover:
            db.set_setting(f"cover_{item_id}", "skip")
        else:
            db.set_setting(f"cover_{item_id}", "")

        updated_item = db.get_wishlist_item(item_id)
        return jsonify({'message': 'Item bijgewerkt', 'item': updated_item})
    except Exception as e:
        return jsonify({'error': f'Server fout: {str(e)}'}), 500


@app.route('/api/cover/<int:item_id>', methods=['DELETE'])
@requires_auth
def api_delete_cover(item_id: int):
    """Verwijder cover en markeer als 'niet zoeken'."""
    user = get_current_user()
    item = db.get_wishlist_item(item_id)

    if not item:
        return jsonify({'error': 'Item niet gevonden'}), 404

    if user['role'] != 'admin' and item.get('user_id') != user['id']:
        return jsonify({'error': 'Geen toegang'}), 403

    # "skip" = niet opnieuw zoeken
    db.set_setting(f"cover_{item_id}", "skip")
    return jsonify({'message': 'Cover verwijderd'})


@app.route('/api/wishlist/<int:item_id>', methods=['DELETE'])
@requires_auth
def api_delete_wishlist(item_id: int):
    """Verwijder item uit wishlist. User kan alleen eigen items verwijderen."""
    user = get_current_user()
    item = db.get_wishlist_item(item_id)

    if not item:
        return jsonify({'error': 'Item niet gevonden'}), 404

    if user['role'] != 'admin' and item.get('user_id') != user['id']:
        return jsonify({'error': 'Je kunt alleen je eigen items verwijderen'}), 403

    deleted = db.delete_wishlist_item(item_id)

    if deleted:
        return jsonify({'message': 'Item verwijderd'}), 200
    else:
        return jsonify({'error': 'Item niet gevonden'}), 404


@app.route('/api/wishlist/bulk-delete', methods=['POST'])
@requires_auth
@requires_admin
def api_bulk_delete_wishlist():
    """Verwijder alle items met een specifieke status (admin only)."""
    data = request.get_json()

    if not data or 'status' not in data:
        return jsonify({'error': 'Status is verplicht'}), 400

    status = data['status']

    valid_statuses = ['pending', 'searching', 'found', 'importing', 'shelved', 'failed']
    if status not in valid_statuses:
        return jsonify({'error': f'Ongeldige status. Gebruik: {", ".join(valid_statuses)}'}), 400

    try:
        deleted_count = db.bulk_delete_by_status(status)
        return jsonify({
            'message': f'{deleted_count} item(s) verwijderd',
            'deleted': deleted_count
        }), 200
    except Exception as e:
        return jsonify({'error': f'Server fout: {str(e)}'}), 500


@app.route('/api/wishlist/<int:item_id>/retry', methods=['POST'])
@requires_auth
def api_retry_search(item_id: int):
    """Zoek direct opnieuw naar dit item (in achtergrondthread)."""
    user = get_current_user()
    item = db.get_wishlist_item(item_id)
    if not item:
        return jsonify({'error': 'Item niet gevonden'}), 404

    if user['role'] != 'admin' and item.get('user_id') != user['id']:
        return jsonify({'error': 'Geen toegang'}), 403

    db.update_wishlist_status(item_id, 'pending', error_message=None)
    db.add_log(item_id, 'info', 'Handmatig opnieuw zoeken gestart')

    # Direct zoeken in achtergrondthread
    def _search_single():
        try:
            from worker import process_item
            fresh_item = db.get_wishlist_item(item_id)
            if fresh_item and fresh_item['status'] == 'pending':
                process_item(fresh_item)
        except Exception as e:
            db.add_log(item_id, 'error', f'Zoekfout: {e}')

    thread = threading.Thread(target=_search_single, daemon=True)
    thread.start()

    return jsonify({'message': 'Zoekactie gestart'}), 202


# Lock om te voorkomen dat meerdere zoekacties tegelijk draaien
_search_lock = threading.Lock()
_search_running = False


def _run_search_now():
    """Draai zoekactie voor alle pending items in achtergrondthread."""
    global _search_running
    try:
        from worker import process_item
        pending = db.get_wishlist_items(status='pending')
        db.add_log(None, 'info', f'Handmatige zoekactie gestart voor {len(pending)} item(s)')
        for item in pending:
            process_item(item)
    except Exception as e:
        db.add_log(None, 'error', f'Handmatige zoekactie fout: {e}')
    finally:
        _search_running = False


@app.route('/api/search/start', methods=['POST'])
@requires_auth
def api_start_search():
    """Start direct een zoekactie voor alle pending items."""
    global _search_running

    if _search_running:
        return jsonify({'error': 'Er draait al een zoekactie'}), 409

    pending = db.get_wishlist_items(status='pending')
    if not pending:
        return jsonify({'error': 'Geen pending items om te zoeken'}), 404

    _search_running = True
    thread = threading.Thread(target=_run_search_now, daemon=True)
    thread.start()

    return jsonify({
        'message': f'Zoekactie gestart voor {len(pending)} item(s)'
    }), 202


@app.route('/api/wishlist/<int:item_id>/status', methods=['PUT'])
@requires_auth
@requires_admin
def api_update_status(item_id: int):
    """Update status van wishlist item (admin only)."""
    data = request.get_json()

    if not data or 'status' not in data:
        return jsonify({'error': 'Status vereist'}), 400

    item = db.get_wishlist_item(item_id)
    if not item:
        return jsonify({'error': 'Item niet gevonden'}), 404

    db.update_wishlist_status(
        item_id=item_id,
        status=data['status'],
        nzb_url=data.get('nzb_url'),
        error_message=data.get('error_message')
    )

    return jsonify({'message': 'Status bijgewerkt'}), 200


@app.route('/api/cover/<int:item_id>', methods=['GET'])
@requires_auth
def api_get_cover(item_id: int):
    """Haal boekcover URL op. Fallback chain: Google Books → Open Library."""
    item = db.get_wishlist_item(item_id)
    if not item:
        return jsonify({'cover_url': None}), 404

    # Check cache
    cache_key = f"cover_{item_id}"
    cached = db.get_setting(cache_key)
    if cached == 'skip':
        return jsonify({'cover_url': None})  # Gebruiker wil geen cover
    if cached is not None and cached != '':
        return jsonify({'cover_url': f"/api/cover-image/{item_id}"})

    # Fallback chain
    cover_url = (
        _fetch_google_books_cover(item['author'], item['title']) or
        _fetch_openlibrary_cover(item['author'], item['title'])
    )

    # Cache resultaat (ook lege string = "niet gevonden")
    db.set_setting(cache_key, cover_url or '')

    # Geef proxy URL terug zodat frontend geen CORS issues heeft
    if cover_url:
        import base64
        proxy_url = f"/api/cover-image/{item_id}"
        return jsonify({'cover_url': proxy_url})

    return jsonify({'cover_url': None})


@app.route('/api/cover-image/<int:item_id>', methods=['GET'])
@requires_auth
def api_cover_image(item_id: int):
    """Proxy voor boekcover afbeeldingen — voorkomt CORS issues."""
    import requests as req

    cache_key = f"cover_{item_id}"
    cover_url = db.get_setting(cache_key)

    if not cover_url:
        return Response(status=404)

    try:
        resp = req.get(cover_url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; WishlistBot/1.0)'
        })
        if resp.status_code != 200:
            return Response(status=resp.status_code)

        content_type = resp.headers.get('Content-Type', 'image/jpeg')
        return Response(
            resp.content,
            content_type=content_type,
            headers={'Cache-Control': 'public, max-age=86400'}  # 24h cache
        )
    except Exception:
        return Response(status=502)


def _normalize_for_search(text: str) -> str:
    """Normaliseer tekst voor zoekopdrachten."""
    import unicodedata
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def _fetch_google_books_cover(author: str, title: str) -> str | None:
    """Zoek boekcover via Google Books API met auteur+titel validatie."""
    import requests as req
    import urllib.parse

    # Gebruik intitle: en inauthor: voor preciezere resultaten
    # Pak alleen achternaam van auteur voor betere matching
    author_parts = author.strip().split()
    author_last = author_parts[-1] if author_parts else author

    queries = [
        f"intitle:{urllib.parse.quote(title)}+inauthor:{urllib.parse.quote(author_last)}",
        f"intitle:{urllib.parse.quote(title)}+inauthor:{urllib.parse.quote(author)}",
    ]

    norm_author = _normalize_for_search(author_last)
    norm_title = _normalize_for_search(title)

    for query in queries:
        try:
            url = f"https://www.googleapis.com/books/v1/volumes?q={query}&maxResults=5&fields=items(volumeInfo)"
            resp = req.get(url, timeout=8)
            if resp.status_code != 200:
                continue

            data = resp.json()
            for item in data.get("items", []):
                vol = item.get("volumeInfo", {})
                links = vol.get("imageLinks", {})
                cover = links.get("thumbnail") or links.get("smallThumbnail")
                if not cover:
                    continue

                # Valideer: auteur en titel moeten matchen
                result_title = _normalize_for_search(vol.get("title", ""))
                result_authors = [_normalize_for_search(a) for a in vol.get("authors", [])]

                title_ok = norm_title in result_title or result_title in norm_title
                author_ok = any(norm_author in a or a in norm_author for a in result_authors)

                if title_ok and author_ok:
                    cover = cover.replace("http://", "https://")
                    cover = cover.replace("&edge=curl", "")
                    cover = cover.replace("zoom=1", "zoom=2")
                    return cover

        except Exception:
            continue

    return None


def _fetch_openlibrary_cover(author: str, title: str) -> str | None:
    """Zoek boekcover via Open Library Search API."""
    import requests as req
    import urllib.parse

    queries = [
        f"title={urllib.parse.quote(title)}&author={urllib.parse.quote(author)}",
        f"title={urllib.parse.quote(title)}",
    ]

    for query in queries:
        try:
            url = f"https://openlibrary.org/search.json?{query}&limit=3&fields=cover_i,title,author_name"
            resp = req.get(url, timeout=8)
            if resp.status_code != 200:
                continue

            data = resp.json()
            docs = data.get("docs", [])

            for doc in docs:
                cover_id = doc.get("cover_i")
                if cover_id:
                    return f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"

        except Exception:
            continue

    return None


@app.route('/api/logs', methods=['GET'])
@requires_auth
def api_get_logs():
    """Haal logs op."""
    wishlist_id = request.args.get('wishlist_id', type=int)
    limit = request.args.get('limit', type=int, default=100)

    logs = db.get_logs(wishlist_id=wishlist_id, limit=limit)
    return jsonify({'logs': logs})


@app.route('/api/stats', methods=['GET'])
@requires_auth
def api_get_stats():
    """Haal statistieken op."""
    items = db.get_wishlist_items()
    logs = db.get_logs(limit=10)

    stats = {
        'total': len(items),
        'pending': len([i for i in items if i['status'] == 'pending']),
        'searching': len([i for i in items if i['status'] == 'searching']),
        'found': len([i for i in items if i['status'] == 'found']),
        'importing': len([i for i in items if i['status'] == 'importing']),
        'shelved': len([i for i in items if i['status'] == 'shelved']),
        'failed': len([i for i in items if i['status'] == 'failed']),
        'recent_logs': logs
    }

    return jsonify(stats)


@app.route('/api/shelves', methods=['GET'])
@requires_auth
def api_get_shelves():
    """Haal boekenplanken op. Admin ziet alles, user ziet alleen toegewezen planken."""
    if not calibreweb.is_configured():
        return jsonify({'shelves': [], 'configured': False})

    try:
        all_shelves = calibreweb.fetch_shelves()

        user = get_current_user()
        if user['role'] != 'admin' and user['allowed_shelves']:
            # Filter planken voor gewone users
            shelves = [s for s in all_shelves if s['name'] in user['allowed_shelves']]
        else:
            shelves = all_shelves

        return jsonify({'shelves': shelves, 'configured': True})
    except Exception as e:
        return jsonify({
            'shelves': [],
            'configured': True,
            'error': f'Calibre-Web fout: {e}'
        })


@app.route('/api/settings', methods=['GET'])
@requires_auth
def api_get_settings():
    """Haal alle instellingen op."""
    settings = {
        'logging_enabled': db.get_setting('logging_enabled', 'true') == 'true',
    }
    return jsonify(settings)


@app.route('/api/settings', methods=['PUT'])
@requires_auth
@requires_admin
def api_update_settings():
    """Update instellingen (admin only)."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Geen data ontvangen'}), 400

    if 'logging_enabled' in data:
        db.set_setting('logging_enabled', 'true' if data['logging_enabled'] else 'false')

    return jsonify({'message': 'Instellingen opgeslagen'})


# ===== API: ADMIN USER MANAGEMENT =====

@app.route('/api/admin/users', methods=['GET'])
@requires_auth
@requires_admin
def api_admin_get_users():
    """Haal alle users op met auto-login links (admin only)."""
    import hmac
    import hashlib
    from datetime import datetime

    users = db.get_all_users()

    # Genereer auto-login URL per user
    secret = app.config['SECRET_KEY']
    ts = datetime.now().isoformat()
    for user in users:
        token = hmac.new(
            secret.encode(), f"{user['username']}:{ts}".encode(), hashlib.sha256
        ).hexdigest()[:32]
        user['autologin_url'] = f"/autologin?user={user['username']}&token={token}&ts={ts}"

    return jsonify({'users': users})


@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@requires_auth
@requires_admin
def api_admin_update_user(user_id: int):
    """Update user gegevens (admin only)."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Geen data ontvangen'}), 400

    user = db.get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'Gebruiker niet gevonden'}), 404

    updated = db.update_user(
        user_id=user_id,
        email=data.get('email'),
        role=data.get('role'),
        allowed_shelves=data.get('allowed_shelves'),
    )

    if updated:
        return jsonify({'message': 'Gebruiker bijgewerkt'})
    else:
        return jsonify({'error': 'Geen wijzigingen'}), 400


@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@requires_auth
@requires_admin
def api_admin_delete_user(user_id: int):
    """Verwijder user (admin only, niet jezelf)."""
    current = get_current_user()
    if current['id'] == user_id:
        return jsonify({'error': 'Je kunt jezelf niet verwijderen'}), 400

    deleted = db.delete_user(user_id)
    if deleted:
        return jsonify({'message': 'Gebruiker verwijderd'})
    else:
        return jsonify({'error': 'Gebruiker niet gevonden'}), 404


@app.route('/api/admin/reset-covers', methods=['POST'])
@requires_auth
@requires_admin
def api_admin_reset_covers():
    """Reset alle cover caches zodat covers opnieuw gezocht worden."""
    count = db.delete_settings_by_prefix("cover_")
    return jsonify({'message': f'{count} cover cache(s) gewist'})


@app.route('/api/health', methods=['GET'])
def api_health():
    """Health check endpoint (geen auth nodig)."""
    return jsonify({
        'status': 'ok',
        'service': 'wishlist-api'
    })


@app.route('/api/update', methods=['POST'])
@requires_auth
@requires_admin
def api_update():
    """Update applicatie code via git pull (admin only)."""
    import subprocess

    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--git-dir'],
            cwd='/app',
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return jsonify({
                'error': 'Geen git repository gevonden in /app',
                'hint': 'Code is waarschijnlijk handmatig geüpload'
            }), 400

        result = subprocess.run(
            ['git', 'pull', 'origin', 'claude/wishlist-web-interface-80kID'],
            cwd='/app',
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            db.add_log(None, 'info', f'Code update: {result.stdout.strip()}')
            return jsonify({
                'message': 'Update succesvol',
                'output': result.stdout,
                'restart_required': True
            }), 200
        else:
            return jsonify({
                'error': 'Git pull mislukt',
                'output': result.stderr
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Git pull timeout'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ===== STARTUP =====

def initialize():
    """Initialiseer applicatie bij startup."""
    db.init_db()

    txt_path = os.environ.get("WISHLIST_FILE", "/data/wishlist.txt")
    if os.path.exists(txt_path):
        db.migrate_from_txt(txt_path)
        import shutil
        backup_path = txt_path + ".backup"
        shutil.copy(txt_path, backup_path)
        os.remove(txt_path)
        print(f"Wishlist.txt gemigreerd en backup gemaakt: {backup_path}")


if __name__ == '__main__':
    initialize()

    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', '5000'))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'

    print(f"Wishlist Web UI gestart op http://{host}:{port}")

    app.run(host=host, port=port, debug=debug)
