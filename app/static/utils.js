/* ── MASTER CONTROL — Utilities ───────────────────────────────── */

const TAG_COLORS = {
    'rag':           '#42a5f5',
    'ml':            '#ab47bc',
    'fine-tuning':   '#ce93d8',
    'web':           '#66bb6a',
    'finance':       '#ffa726',
    'hardware':      '#ef5350',
    'infra':         '#78909c',
    'nlp':           '#29b6f6',
    'search':        '#5c6bc0',
    'biomedical':    '#26a69a',
    'data-pipeline': '#8d6e63',
    'visualization': '#ffca28',
    'other':         '#546e7a',
};

function getTagColor(tag) {
    return TAG_COLORS[tag] || '#546e7a';
}

function getPrimaryTag(tags) {
    return tags && tags.length > 0 ? tags[0] : 'other';
}

function formatDate(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    const now = new Date();
    const diffDays = Math.floor((now - d) / (1000 * 60 * 60 * 24));
    if (diffDays === 0) return 'today';
    if (diffDays === 1) return 'yesterday';
    if (diffDays < 30) return `${diffDays}d ago`;
    return d.toLocaleDateString();
}

function formatSize(mb) {
    if (mb < 1) return `${Math.round(mb * 1024)} KB`;
    if (mb < 1024) return `${mb} MB`;
    return `${(mb / 1024).toFixed(1)} GB`;
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function apiFetch(path, opts = {}) {
    const resp = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    if (resp.status === 204) return null;
    return resp.json();
}
