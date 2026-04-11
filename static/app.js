// Wishlist Manager
let currentFilter = 'all';
let wishlistData = { items: [], stats: {} };
let currentUser = null;

// ===== INIT =====
document.addEventListener('DOMContentLoaded', () => {
    loadCurrentUser();
    loadWishlist();
    loadLogs();
    loadShelves();
    loadSettings();
    setupEventListeners();

    setInterval(() => {
        loadWishlist();
        loadLogs();
    }, 30000);
});

async function loadCurrentUser() {
    try {
        const response = await fetch('/api/me');
        if (response.status === 401) { window.location.href = '/login'; return; }
        if (!response.ok) return;

        currentUser = await response.json();

        const sidebarUser = document.getElementById('sidebar-user');
        if (sidebarUser) sidebarUser.textContent = currentUser.username;

        const sidebarTitle = document.getElementById('sidebar-title');
        if (sidebarTitle) sidebarTitle.textContent = `Boekjes`;

        if (currentUser.role === 'admin') {
            const navAdmin = document.getElementById('nav-admin');
            if (navAdmin) navAdmin.style.display = '';
        }
    } catch (error) {
        console.error('Error loading user:', error);
    }
}

// ===== EVENT LISTENERS =====
function setupEventListeners() {
    document.getElementById('add-form').addEventListener('submit', handleAddItem);

    document.querySelectorAll('.filter-tab').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.filter-tab').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            currentFilter = e.target.dataset.status;
            renderWishlist();
        });
    });
}

// ===== SIDEBAR TOGGLE =====
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
    document.getElementById('sidebar-overlay').classList.toggle('open');
}

// ===== API CALLS =====
async function loadShelves() {
    try {
        const response = await fetch('/api/shelves');
        if (!response.ok) return;

        const data = await response.json();
        if (!data.configured || !data.shelves || data.shelves.length === 0) return;

        const select = document.getElementById('shelf');
        const group = document.getElementById('shelf-group');

        data.shelves.forEach(shelf => {
            const option = document.createElement('option');
            option.value = shelf.name;
            option.textContent = `${shelf.name} (${shelf.count})`;
            select.appendChild(option);
        });

        group.style.display = '';
    } catch (error) {
        console.error('Error loading shelves:', error);
    }
}

async function loadWishlist() {
    try {
        const response = await fetch('/api/wishlist');
        if (response.status === 401) { window.location.href = '/login'; return; }
        if (!response.ok) throw new Error('Laden mislukt');

        wishlistData = await response.json();
        updateStats(wishlistData.stats);
        renderWishlist();
    } catch (error) {
        console.error('Error loading wishlist:', error);
        document.getElementById('wishlist-container').innerHTML = `
            <div class="empty-state">
                <h3>Fout bij laden</h3>
                <p>Kon wishlist niet laden</p>
            </div>`;
    } finally {
        document.getElementById('loading').style.display = 'none';
    }
}

async function loadLogs() {
    try {
        const response = await fetch('/api/logs?limit=20');
        if (!response.ok) return;
        const data = await response.json();
        renderLogs(data.logs);
    } catch (error) {
        console.error('Error loading logs:', error);
    }
}

async function handleAddItem(e) {
    e.preventDefault();
    const author = document.getElementById('author').value.trim();
    const title = document.getElementById('title').value.trim();
    const shelfSelect = document.getElementById('shelf');
    const shelfName = shelfSelect ? shelfSelect.value : '';
    const messageEl = document.getElementById('add-message');

    if (!author || !title) {
        showMessage(messageEl, 'Vul beide velden in', 'error');
        return;
    }

    const body = { author, title };
    if (shelfName) body.shelf_name = shelfName;

    try {
        const response = await fetch('/api/wishlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            credentials: 'include'
        });

        const data = await response.json();

        if (response.ok) {
            const shelfMsg = shelfName ? ` \u2192 ${shelfName}` : '';
            showMessage(messageEl, `${author} - "${title}" toegevoegd!${shelfMsg}`, 'success');
            document.getElementById('add-form').reset();
            loadWishlist();
            loadLogs();
        } else {
            showMessage(messageEl, data.error || 'Toevoegen mislukt', 'error');
        }
    } catch (error) {
        showMessage(messageEl, 'Netwerkfout: ' + error.message, 'error');
    }
}

async function deleteItem(itemId, title) {
    if (!confirm(`"${title}" verwijderen?`)) return;

    try {
        const response = await fetch(`/api/wishlist/${itemId}`, { method: 'DELETE' });
        if (response.ok) { loadWishlist(); loadLogs(); }
        else alert('Verwijderen mislukt');
    } catch (error) {
        alert('Netwerkfout: ' + error.message);
    }
}

async function startSearchNow() {
    const btn = document.getElementById('btn-search-now');
    btn.disabled = true;
    const origText = btn.innerHTML;
    btn.innerHTML = '<svg viewBox="0 0 20 20" width="16" height="16"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="20" stroke-dashoffset="0"><animateTransform attributeName="transform" type="rotate" dur="0.8s" from="0 10 10" to="360 10 10" repeatCount="indefinite"/></circle></svg> Bezig...';

    try {
        const response = await fetch('/api/search/start', {
            method: 'POST',
            credentials: 'include'
        });

        if (response.ok) {
            loadWishlist();
            loadLogs();
        } else {
            const data = await response.json();
            alert(data.error || 'Zoekactie starten mislukt');
        }
    } catch (error) {
        alert('Netwerkfout: ' + error.message);
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            btn.innerHTML = origText;
        }, 3000);
    }
}

async function retrySearch(itemId) {
    try {
        const response = await fetch(`/api/wishlist/${itemId}/retry`, {
            method: 'POST',
            credentials: 'include'
        });
        if (response.ok) { loadWishlist(); loadLogs(); }
        else {
            const data = await response.json();
            alert(data.error || 'Opnieuw zoeken mislukt');
        }
    } catch (error) {
        alert('Netwerkfout: ' + error.message);
    }
}

async function deleteAllFound() {
    const doneItems = wishlistData.items.filter(item =>
        item.status === 'found' || item.status === 'shelved'
    );

    if (doneItems.length === 0) {
        alert('Geen afgeronde items om te verwijderen');
        return;
    }

    if (!confirm(`${doneItems.length} afgeronde item(s) verwijderen?`)) return;

    try {
        let totalDeleted = 0;
        for (const status of ['found', 'shelved']) {
            const response = await fetch('/api/wishlist/bulk-delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status }),
                credentials: 'include'
            });
            if (response.ok) {
                const data = await response.json();
                totalDeleted += data.deleted;
            }
        }
        loadWishlist();
        loadLogs();
    } catch (error) {
        alert('Netwerkfout: ' + error.message);
    }
}

// ===== SETTINGS =====
function toggleSettings() {
    const panel = document.getElementById('settings-panel');
    panel.style.display = panel.style.display === 'none' ? '' : 'none';
}

async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        if (!response.ok) return;
        const data = await response.json();
        document.getElementById('setting-logging').checked = data.logging_enabled;
    } catch (error) {
        console.error('Error loading settings:', error);
    }
}

async function saveSetting(key, value) {
    try {
        const response = await fetch('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [key]: value }),
            credentials: 'include'
        });
        if (!response.ok) alert('Instelling opslaan mislukt');
    } catch (error) {
        alert('Netwerkfout: ' + error.message);
    }
}

// ===== RENDER FUNCTIONS =====
function updateStats(stats) {
    document.getElementById('stat-total').textContent = stats.total || 0;
    document.getElementById('stat-pending').textContent = stats.pending || 0;
    document.getElementById('stat-searching').textContent = stats.searching || 0;
    document.getElementById('stat-found').textContent = (stats.found || 0) + (stats.importing || 0) + (stats.shelved || 0);
}

function getStatusText(status) {
    return {
        'pending': 'Pending',
        'searching': 'Searching',
        'found': 'Found',
        'importing': 'Importing',
        'shelved': 'Shelved',
        'failed': 'Failed'
    }[status] || status;
}

function getCoverGradient(title) {
    // Generate a consistent color based on title
    let hash = 0;
    for (let i = 0; i < (title || '').length; i++) {
        hash = title.charCodeAt(i) + ((hash << 5) - hash);
    }
    const gradients = [
        'linear-gradient(135deg, #e6f7f5 0%, #d1eef9 100%)',
        'linear-gradient(135deg, #fdf0ea 0%, #fce4d6 100%)',
        'linear-gradient(135deg, #e8f1fb 0%, #d6e5f5 100%)',
        'linear-gradient(135deg, #f3e8f9 0%, #e8d5f0 100%)',
        'linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%)',
        'linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%)',
    ];
    return gradients[Math.abs(hash) % gradients.length];
}

function renderWishlist() {
    const container = document.getElementById('wishlist-container');

    let items = wishlistData.items;
    if (currentFilter !== 'all') {
        items = items.filter(item => item.status === currentFilter);
    }

    if (items.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <h3>Geen items</h3>
                <p>${currentFilter === 'all' ? 'Voeg je eerste boek toe!' : `Geen items met status "${currentFilter}"`}</p>
            </div>`;
        return;
    }

    const doneStatuses = ['found', 'shelved'];
    const activeItems = items.filter(item => !doneStatuses.includes(item.status));
    const doneItems = items.filter(item => doneStatuses.includes(item.status));

    const renderCard = (item) => {
        const gradient = getCoverGradient(item.title);
        const addedBy = item.added_by ? `<span class="meta-tag"><svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clip-rule="evenodd"/></svg>${escapeHtml(item.added_by)}</span>` : '';
        const shelfTag = item.shelf_name ? `<span class="meta-tag shelf-tag"><svg viewBox="0 0 20 20" fill="currentColor"><path d="M9 4.804A7.968 7.968 0 005.5 4c-1.255 0-2.443.29-3.5.804v10A7.969 7.969 0 015.5 14c1.669 0 3.218.51 4.5 1.385A7.962 7.962 0 0114.5 14c1.255 0 2.443.29 3.5.804v-10A7.968 7.968 0 0014.5 4c-1.255 0-2.443.29-3.5.804V15a1 1 0 11-2 0V4.804z"/></svg>${escapeHtml(item.shelf_name)}</span>` : '';

        let actionBtns = '';
        if (item.status !== 'searching') {
            actionBtns += `<button class="card-btn" onclick="retrySearch(${item.id})"><svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/></svg>Search again</button>`;
        }
        actionBtns += `<button class="card-btn btn-delete" onclick="deleteItem(${item.id}, '${escapeHtml(item.title)}')"><svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>Delete</button>`;

        return `
        <div class="book-card">
            <div class="book-cover" data-item-id="${item.id}" style="background: ${gradient}">
                <div class="book-cover-placeholder">
                    <svg viewBox="0 0 64 64" fill="none"><rect x="12" y="8" width="40" height="48" rx="4" fill="currentColor" opacity="0.15"/><rect x="16" y="12" width="32" height="40" rx="2" fill="white" opacity="0.5"/><line x1="22" y1="22" x2="42" y2="22" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="22" y1="28" x2="42" y2="28" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="22" y1="34" x2="36" y2="34" stroke="currentColor" stroke-width="2" opacity="0.2"/></svg>
                </div>
                <span class="status-pill status-${item.status}">${getStatusText(item.status)}</span>
            </div>
            <div class="book-info">
                <div class="book-title">${escapeHtml(item.title)}</div>
                <div class="book-author">${escapeHtml(item.author)}</div>
                <div class="book-meta">
                    ${shelfTag}
                    ${addedBy}
                </div>
            </div>
            <div class="book-footer">
                <span class="book-date">ADDED ${formatDate(item.added_date).toUpperCase()}</span>
                <div class="book-actions">
                    ${actionBtns}
                </div>
            </div>
        </div>`;
    };

    let html = '';

    if (activeItems.length > 0) {
        html += activeItems.map(renderCard).join('');
    }

    if (activeItems.length > 0 && doneItems.length > 0) {
        html += '<div class="grid-separator">Gevonden</div>';
    }

    if (doneItems.length > 0) {
        html += doneItems.map(renderCard).join('');
    }

    container.innerHTML = html;
    loadCovers();
}

// ===== COVER LOADING =====
const coverCache = new Map();

async function loadCovers() {
    const coverEls = document.querySelectorAll('.book-cover[data-item-id]');

    for (const el of coverEls) {
        const itemId = el.dataset.itemId;
        if (!itemId) continue;

        // Check in-memory cache
        if (coverCache.has(itemId)) {
            const url = coverCache.get(itemId);
            if (url) applyCover(el, url);
            continue;
        }

        // Fetch van backend (die cached in DB)
        try {
            const response = await fetch(`/api/cover/${itemId}`);
            if (!response.ok) continue;

            const data = await response.json();
            coverCache.set(itemId, data.cover_url);

            if (data.cover_url) {
                applyCover(el, data.cover_url);
            }
        } catch (e) {
            // Silently skip
        }
    }
}

function applyCover(el, url) {
    const img = new Image();
    img.onload = () => {
        el.style.background = `url('${url}') center/cover no-repeat`;
        const placeholder = el.querySelector('.book-cover-placeholder');
        if (placeholder) placeholder.style.display = 'none';
    };
    img.src = url;
}

function renderLogs(logs) {
    const container = document.getElementById('logs-container');

    if (!logs || logs.length === 0) {
        container.innerHTML = '<div class="empty-state"><p>Nog geen activiteit</p></div>';
        return;
    }

    container.innerHTML = logs.slice(0, 10).map(log => `
        <div class="log-entry log-${log.level}">
            <span class="log-time">${formatDateTime(log.timestamp)}</span>
            ${log.author ? `<span class="log-item">${escapeHtml(log.author)} - "${escapeHtml(log.title)}":</span>` : ''}
            <span>${escapeHtml(log.message)}</span>
        </div>
    `).join('');
}

// ===== UTILITY =====
function showMessage(element, message, type) {
    element.textContent = message;
    element.className = `toast-message show ${type}`;
    setTimeout(() => element.classList.remove('show'), 5000);
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleDateString('nl-NL', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatDateTime(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('nl-NL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}
