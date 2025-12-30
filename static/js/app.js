// Radio Automation - Main JavaScript

// Socket.IO connection
let socket = null;

document.addEventListener('DOMContentLoaded', function() {
    initSocket();
    updateStatus();
    setInterval(updateStatus, 10000); // Update every 10 seconds
});

function initSocket() {
    try {
        socket = io();

        socket.on('connect', function() {
            console.log('WebSocket connected');
        });

        socket.on('disconnect', function() {
            console.log('WebSocket disconnected');
        });

        socket.on('now_playing', function(data) {
            updateNowPlaying(data);
        });

        socket.on('queue_updated', function(data) {
            // Could update queue display here
        });
    } catch (e) {
        console.log('WebSocket not available:', e);
    }
}

function updateNowPlaying(data) {
    const titleEl = document.getElementById('now-playing-title');
    const artistEl = document.getElementById('now-playing-artist');

    if (titleEl) {
        titleEl.textContent = data.title || 'Unbekannt';
    }
    if (artistEl) {
        artistEl.textContent = data.artist ? ' - ' + data.artist : '';
    }
}

async function updateStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();

        // Update now playing
        if (data.current_track) {
            updateNowPlaying(data.current_track);
        }

        // Update listener count
        const listenerEl = document.getElementById('listener-count');
        if (listenerEl) {
            listenerEl.textContent = data.listeners || 0;
        }
    } catch (e) {
        console.log('Status update failed:', e);
    }
}

function skipTrack() {
    fetch('/api/skip', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('Titel wird übersprungen...', 'info');
            } else {
                showToast('Fehler beim Überspringen', 'danger');
            }
        })
        .catch(error => {
            showToast('Fehler: ' + error, 'danger');
        });
}

// Toast notification system
function showToast(message, type = 'info') {
    // Create toast container if it doesn't exist
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
    }

    // Create toast element
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.id = toastId;
    toast.className = `toast align-items-center text-bg-${type} border-0`;
    toast.setAttribute('role', 'alert');
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;

    container.appendChild(toast);

    // Initialize and show toast
    const bsToast = new bootstrap.Toast(toast, { delay: 3000 });
    bsToast.show();

    // Remove toast element after it's hidden
    toast.addEventListener('hidden.bs.toast', function() {
        toast.remove();
    });
}

// Utility functions
function formatDuration(seconds) {
    if (!seconds) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatDateTime(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Confirmation dialogs
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

// Loading overlay
function showLoading() {
    let overlay = document.getElementById('loading-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'loading-overlay';
        overlay.className = 'position-fixed top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center';
        overlay.style.background = 'rgba(0,0,0,0.5)';
        overlay.style.zIndex = '9999';
        overlay.innerHTML = `
            <div class="spinner-border text-light" role="status">
                <span class="visually-hidden">Laden...</span>
            </div>
        `;
        document.body.appendChild(overlay);
    }
    overlay.style.display = 'flex';
}

function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.style.display = 'none';
    }
}

// Fetch wrapper with error handling
async function apiFetch(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Ein Fehler ist aufgetreten');
        }

        return data;
    } catch (error) {
        showToast(error.message, 'danger');
        throw error;
    }
}

// Debounce function for search inputs
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Skip track with Ctrl+S (when not in input)
    if (e.ctrlKey && e.key === 's' && document.activeElement.tagName !== 'INPUT') {
        e.preventDefault();
        skipTrack();
    }
});
