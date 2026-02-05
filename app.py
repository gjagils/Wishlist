#!/usr/bin/env python3
"""
Flask web applicatie voor Wishlist beheer.
Biedt web UI en REST API met basic authentication.
"""
import os
import re
import threading
from functools import wraps
from flask import Flask, request, jsonify, render_template_string, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

import database as db
import calibreweb

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Authenticatie configuratie
USERNAME = os.environ.get('WEB_USERNAME', 'admin')
PASSWORD_HASH = generate_password_hash(os.environ.get('WEB_PASSWORD', 'wishlist'))


def check_auth(username: str, password: str) -> bool:
    """Controleer gebruikersnaam en wachtwoord."""
    return username == USERNAME and check_password_hash(PASSWORD_HASH, password)


def authenticate():
    """Stuur 401 response voor authenticatie."""
    return jsonify({'error': 'Authenticatie vereist'}), 401, {
        'WWW-Authenticate': 'Basic realm="Wishlist"'
    }


def requires_auth(f):
    """Decorator voor endpoints die authenticatie vereisen."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


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
    # Cache static files for 1 hour, but allow revalidation
    response.headers['Cache-Control'] = 'public, max-age=3600, must-revalidate'
    return response


# ===== API ENDPOINTS =====

@app.route('/api/wishlist', methods=['GET'])
@requires_auth
def api_get_wishlist():
    """Haal alle wishlist items op."""
    status = request.args.get('status')
    items = db.get_wishlist_items(status=status)

    # Voeg count per status toe
    all_items = db.get_wishlist_items()
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
    item = db.get_wishlist_item(item_id)
    if not item:
        return jsonify({'error': 'Item niet gevonden'}), 404

    # Voeg logs toe
    logs = db.get_logs(wishlist_id=item_id)
    item['logs'] = logs

    return jsonify(item)


@app.route('/api/wishlist', methods=['POST'])
@requires_auth
def api_add_wishlist():
    """Voeg nieuw item toe aan wishlist."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Geen data ontvangen'}), 400

    author = data.get('author', '').strip()
    title = data.get('title', '').strip()

    if not author or not title:
        return jsonify({'error': 'Auteur en titel zijn verplicht'}), 400

    try:
        item_id = db.add_wishlist_item(
            author=author,
            title=title,
            added_via=data.get('added_via', 'web'),
            shelf_name=data.get('shelf_name')
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


@app.route('/api/wishlist/<int:item_id>', methods=['DELETE'])
@requires_auth
def api_delete_wishlist(item_id: int):
    """Verwijder item uit wishlist."""
    deleted = db.delete_wishlist_item(item_id)

    if deleted:
        return jsonify({'message': 'Item verwijderd'}), 200
    else:
        return jsonify({'error': 'Item niet gevonden'}), 404


@app.route('/api/wishlist/bulk-delete', methods=['POST'])
@requires_auth
def api_bulk_delete_wishlist():
    """Verwijder alle items met een specifieke status."""
    data = request.get_json()

    if not data or 'status' not in data:
        return jsonify({'error': 'Status is verplicht'}), 400

    status = data['status']

    # Valideer status
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
    """Zet item terug naar pending zodat worker opnieuw zoekt."""
    item = db.get_wishlist_item(item_id)
    if not item:
        return jsonify({'error': 'Item niet gevonden'}), 404

    db.update_wishlist_status(item_id, 'pending', error_message=None)
    db.add_log(item_id, 'info', 'Handmatig opnieuw zoeken gestart')

    return jsonify({'message': 'Zoekactie opnieuw gestart'}), 200


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
def api_update_status(item_id: int):
    """Update status van wishlist item (voor worker)."""
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
    """Haal boekenplanken op uit Calibre-Web."""
    if not calibreweb.is_configured():
        return jsonify({'shelves': [], 'configured': False})

    try:
        shelves = calibreweb.fetch_shelves()
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
def api_update_settings():
    """Update instellingen."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Geen data ontvangen'}), 400

    if 'logging_enabled' in data:
        db.set_setting('logging_enabled', 'true' if data['logging_enabled'] else 'false')

    return jsonify({'message': 'Instellingen opgeslagen'})


@app.route('/api/health', methods=['GET'])
def api_health():
    """Health check endpoint (geen auth nodig)."""
    return jsonify({
        'status': 'ok',
        'service': 'wishlist-api'
    })


@app.route('/api/update', methods=['POST'])
@requires_auth
def api_update():
    """Update applicatie code via git pull."""
    import subprocess

    try:
        # Check of we in een git repository zitten
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

        # Git pull uitvoeren
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
    # Initialiseer database
    db.init_db()

    # Migreer van wishlist.txt indien aanwezig
    txt_path = os.environ.get("WISHLIST_FILE", "/data/wishlist.txt")
    if os.path.exists(txt_path):
        db.migrate_from_txt(txt_path)
        # Backup maken en verwijderen
        import shutil
        backup_path = txt_path + ".backup"
        shutil.copy(txt_path, backup_path)
        os.remove(txt_path)
        print(f"✓ Wishlist.txt gemigreerd en backup gemaakt: {backup_path}")


if __name__ == '__main__':
    initialize()

    # Start Flask server
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', '5000'))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'

    print(f"✓ Wishlist Web UI gestart op http://{host}:{port}")
    print(f"✓ Login: {USERNAME} / <WEB_PASSWORD>")

    app.run(host=host, port=port, debug=debug)
