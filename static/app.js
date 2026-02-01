// Wishlist Manager - JavaScript
let currentFilter = 'all';
let wishlistData = { items: [], stats: {} };

// ===== INIT =====
document.addEventListener('DOMContentLoaded', () => {
    loadWishlist();
    loadLogs();
    setupEventListeners();

    // Auto-refresh elke 30 seconden
    setInterval(() => {
        loadWishlist();
        loadLogs();
    }, 30000);
});

// ===== EVENT LISTENERS =====
function setupEventListeners() {
    // Add form
    document.getElementById('add-form').addEventListener('submit', handleAddItem);

    // Filter buttons
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            currentFilter = e.target.dataset.status;
            renderWishlist();
        });
    });
}

// ===== API CALLS =====
async function loadWishlist() {
    try {
        const response = await fetch('/api/wishlist');
        if (!response.ok) throw new Error('Laden mislukt');

        wishlistData = await response.json();
        updateStats(wishlistData.stats);
        renderWishlist();
    } catch (error) {
        console.error('Error loading wishlist:', error);
        showError('wishlist-container', 'Kon wishlist niet laden');
    } finally {
        document.getElementById('loading').style.display = 'none';
    }
}

async function loadLogs() {
    try {
        const response = await fetch('/api/logs?limit=20');
        if (!response.ok) throw new Error('Laden mislukt');

        const data = await response.json();
        renderLogs(data.logs);
    } catch (error) {
        console.error('Error loading logs:', error);
    }
}

async function handleAddItem(e) {
    e.preventDefault();
    console.log('Form submitted!'); // DEBUG

    const author = document.getElementById('author').value.trim();
    const title = document.getElementById('title').value.trim();
    const messageEl = document.getElementById('add-message');

    console.log('Author:', author, 'Title:', title); // DEBUG

    if (!author || !title) {
        showMessage(messageEl, 'Vul beide velden in', 'error');
        return;
    }

    try {
        console.log('Sending POST request...'); // DEBUG
        const response = await fetch('/api/wishlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ author, title }),
            credentials: 'include'  // Zorg dat auth cookies worden meegestuurd
        });

        console.log('Response status:', response.status); // DEBUG

        const data = await response.json();
        console.log('Response data:', data); // DEBUG

        if (response.ok) {
            showMessage(messageEl, `✓ ${author} - "${title}" toegevoegd!`, 'success');
            document.getElementById('add-form').reset();
            loadWishlist();
            loadLogs();
        } else {
            showMessage(messageEl, data.error || 'Toevoegen mislukt', 'error');
        }
    } catch (error) {
        console.error('Fetch error:', error); // DEBUG
        showMessage(messageEl, 'Netwerkfout: ' + error.message, 'error');
    }
}

async function deleteItem(itemId, title) {
    if (!confirm(`Weet je zeker dat je "${title}" wilt verwijderen?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/wishlist/${itemId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            loadWishlist();
            loadLogs();
        } else {
            alert('Verwijderen mislukt');
        }
    } catch (error) {
        alert('Netwerkfout: ' + error.message);
    }
}

async function startSearchNow() {
    const btn = document.getElementById('btn-search-now');
    btn.disabled = true;
    btn.textContent = '⏳ Bezig...';

    try {
        const response = await fetch('/api/search/start', {
            method: 'POST',
            credentials: 'include'
        });

        const data = await response.json();

        if (response.ok) {
            btn.textContent = '✓ Gestart';
            loadWishlist();
            loadLogs();
        } else {
            alert(data.error || 'Zoekactie starten mislukt');
        }
    } catch (error) {
        alert('Netwerkfout: ' + error.message);
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = '🔍 Nu zoeken';
        }, 3000);
    }
}

async function retrySearch(itemId, title) {
    try {
        const response = await fetch(`/api/wishlist/${itemId}/retry`, {
            method: 'POST',
            credentials: 'include'
        });

        if (response.ok) {
            loadWishlist();
            loadLogs();
        } else {
            const data = await response.json();
            alert(data.error || 'Opnieuw zoeken mislukt');
        }
    } catch (error) {
        alert('Netwerkfout: ' + error.message);
    }
}

async function deleteAllFound() {
    const foundItems = wishlistData.items.filter(item => item.status === 'found');

    if (foundItems.length === 0) {
        alert('Geen gevonden items om te verwijderen');
        return;
    }

    if (!confirm(`Weet je zeker dat je alle ${foundItems.length} gevonden item(s) wilt verwijderen?`)) {
        return;
    }

    try {
        const response = await fetch('/api/wishlist/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'found' }),
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            alert(`✓ ${data.deleted} item(s) verwijderd`);
            loadWishlist();
            loadLogs();
        } else {
            const data = await response.json();
            alert(data.error || 'Verwijderen mislukt');
        }
    } catch (error) {
        alert('Netwerkfout: ' + error.message);
    }
}

// ===== RENDER FUNCTIONS =====
function updateStats(stats) {
    document.getElementById('stat-total').innerHTML = `Totaal: <strong>${stats.total}</strong>`;
    document.getElementById('stat-pending').innerHTML = `Pending: <strong>${stats.pending}</strong>`;
    document.getElementById('stat-searching').innerHTML = `Zoeken: <strong>${stats.searching}</strong>`;
    document.getElementById('stat-found').innerHTML = `Gevonden: <strong>${stats.found}</strong>`;
    document.getElementById('stat-failed').innerHTML = `Mislukt: <strong>${stats.failed}</strong>`;
}

function renderWishlist() {
    const container = document.getElementById('wishlist-container');

    // Filter items
    let items = wishlistData.items;
    if (currentFilter !== 'all') {
        items = items.filter(item => item.status === currentFilter);
    }

    if (items.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <h3>Geen items</h3>
                <p>${currentFilter === 'all' ? 'Voeg je eerste item toe!' : `Geen items met status "${currentFilter}"`}</p>
            </div>
        `;
        return;
    }

    // Sorteer items: niet-gevonden eerst, dan gevonden
    const unfoundItems = items.filter(item => item.status !== 'found');
    const foundItems = items.filter(item => item.status === 'found');

    const renderItem = (item) => `
        <div class="wishlist-item">
            <div class="item-header">
                <div class="item-title">
                    <h3>"${escapeHtml(item.title)}"</h3>
                    <div class="item-author">door ${escapeHtml(item.author)}</div>
                </div>
                <div class="item-actions">
                    <span class="status-badge status-${item.status}">${getStatusText(item.status)}</span>
                    ${item.status !== 'searching' ? `<button class="btn btn-secondary" onclick="retrySearch(${item.id}, '${escapeHtml(item.title)}')">Opnieuw zoeken</button>` : ''}
                    <button class="btn btn-danger" onclick="deleteItem(${item.id}, '${escapeHtml(item.title)}')">
                        Verwijder
                    </button>
                </div>
            </div>
            <div class="item-meta">
                <span>📅 Toegevoegd: ${formatDate(item.added_date)}</span>
                <span>📍 Via: ${item.added_via}</span>
                ${item.last_search ? `<span>🔍 Laatste zoek: ${formatDate(item.last_search)}</span>` : ''}
                ${item.error_message ? `<span style="color: var(--danger-color)">⚠️ ${escapeHtml(item.error_message)}</span>` : ''}
            </div>
        </div>
    `;

    let html = '';

    // Render niet-gevonden items
    if (unfoundItems.length > 0) {
        html += unfoundItems.map(renderItem).join('');
    }

    // Voeg scheidingslijn toe als er beide categorieën zijn
    if (unfoundItems.length > 0 && foundItems.length > 0) {
        html += '<div class="items-separator">Gevonden</div>';
    }

    // Render gevonden items
    if (foundItems.length > 0) {
        html += foundItems.map(renderItem).join('');
    }

    container.innerHTML = html;
}

function renderLogs(logs) {
    const container = document.getElementById('logs-container');

    if (logs.length === 0) {
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

// ===== UTILITY FUNCTIONS =====
function showMessage(element, message, type) {
    element.textContent = message;
    element.className = `message show ${type}`;

    setTimeout(() => {
        element.classList.remove('show');
    }, 5000);
}

function showError(containerId, message) {
    document.getElementById(containerId).innerHTML = `
        <div class="empty-state">
            <h3>⚠️ Fout</h3>
            <p>${message}</p>
        </div>
    `;
}

function getStatusText(status) {
    const statusMap = {
        'pending': 'Pending',
        'searching': 'Zoeken...',
        'found': 'Gevonden',
        'failed': 'Mislukt'
    };
    return statusMap[status] || status;
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleDateString('nl-NL', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    });
}

function formatDateTime(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('nl-NL', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
