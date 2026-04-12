/**
 * Wishlist link voor Calibre-Web navigatie.
 *
 * Installatie (linuxserver/calibre-web):
 * 1. Kopieer dit bestand naar /volume1/docker/calibre-web/config/custom/wishlist.js
 * 2. In Calibre-Web Admin → Edit UI Configuration → "Custom Header" veld:
 *    <script src="/static/custom/wishlist.js"></script>
 * 3. Pas WISHLIST_URL en AUTOLOGIN_KEY hieronder aan
 */

(function() {
    // === CONFIGURATIE ===
    var WISHLIST_URL = 'https://wishlist.gerdjan.nl';  // Publieke URL via reverse proxy
    var AUTOLOGIN_KEY = 'wishlist-link-2026';          // Moet matchen met AUTOLOGIN_KEY env var

    // Detecteer huidige gebruiker uit Calibre-Web UI
    function getUsername() {
        // linuxserver/calibre-web: username staat in de navbar dropdown
        var el = document.querySelector('.dropdown-toggle .hidden-sm');
        if (el) return el.textContent.trim();

        el = document.querySelector('.dropdown-toggle');
        if (el) {
            var text = el.textContent.trim();
            // Strip "▼" of andere dropdown indicators
            return text.replace(/[\s▼▾⌄↓]/g, '').trim();
        }

        // Fallback: probeer andere locaties
        el = document.querySelector('#username, .username, [data-username]');
        if (el) return (el.textContent || el.dataset.username || '').trim();

        return '';
    }

    function addWishlistLink() {
        var username = getUsername();
        if (!username) return;

        var url = WISHLIST_URL + '/autologin?user=' +
                  encodeURIComponent(username) + '&key=' +
                  encodeURIComponent(AUTOLOGIN_KEY);

        // Zoek de sidebar navigatie
        var sidebar = document.getElementById('sidebar-nav');
        if (sidebar) {
            var li = document.createElement('li');
            li.className = 'nav-head';
            li.innerHTML = '<a href="' + url + '"><span class="glyphicon glyphicon-heart"></span> Wishlist</a>';
            sidebar.appendChild(li);
            return;
        }

        // Fallback: zoek de navbar
        var navbar = document.querySelector('.navbar-nav');
        if (navbar) {
            var li = document.createElement('li');
            li.innerHTML = '<a href="' + url + '"><span class="glyphicon glyphicon-heart"></span> Wishlist</a>';
            navbar.appendChild(li);
        }
    }

    // Wacht tot DOM geladen is
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', addWishlistLink);
    } else {
        addWishlistLink();
    }
})();
