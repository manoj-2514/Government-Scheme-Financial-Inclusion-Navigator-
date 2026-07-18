/**
 * dashboard.js
 * Fetches session summary from the backend and renders the Dashboard tab:
 *  - Summary stat cards (total checked, eligible, needs more info)
 *  - Profile completeness meter
 *  - Searchable, expandable eligible-scheme cards (tap to see documents)
 *  - Clickable "missing info" chips that jump to chat with a starter message
 *  - Animated SVG bar chart for category breakdown + refresh button
 *
 * All backend-provided text is escaped before rendering (XSS-safe).
 */
import { t } from './translations.js';

const API_BASE_URL = window.API_BASE_URL || 'http://localhost:8000';

function getFieldLabel(field) {
    // Try localized translation first, fall back to English defaults
    const translated = t('profile.' + field);
    if (translated && translated !== 'profile.' + field) return translated;
    const defaults = {
        occupation: 'Occupation',
        state: 'State / UT',
        income: 'Annual Income',
        land_acres: 'Land Owned (acres)',
        age: 'Age',
        category: 'Social Category (SC/ST/OBC/General)',
        gender: 'Gender',
    };
    return defaults[field] || field;
}

// Starter text inserted into the chat input when a missing chip is clicked
const FIELD_PROMPTS = {
    occupation: 'My occupation is ',
    state: 'I live in the state of ',
    income: 'My annual income is ₹',
    land_acres: 'I own land of (acres) ',
    age: 'My age is ',
    category: 'My category is ',
    gender: 'My gender is ',
};

const PROFILE_FIELD_COUNT = 7; // occupation, state, income, land_acres, age, category, gender

const CATEGORY_COLORS = [
    '#E08A2C', '#1F6F5C', '#3B82F6', '#8B5CF6',
    '#EC4899', '#14B8A6', '#F97316', '#6366F1',
];

// Last fetched summary, kept so search filtering re-renders without refetching
let _lastData = null;
let _lastSessionId = null;
let _searchTerm = '';

/** Escape text for safe insertion into innerHTML (XSS protection). */
function esc(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/** Only allow http/https links from data; anything else becomes '#'. */
function safeUrl(url) {
    const u = String(url || '').trim();
    return /^https?:\/\//i.test(u) ? u : '#';
}

/**
 * Fetch summary data from backend and re-render the dashboard.
 * @param {string} sessionId
 */
export async function refreshDashboard(sessionId) {
    const container = document.getElementById('dashboard-view');
    if (!container) return;

    _lastSessionId = sessionId;

    container.innerHTML = `
        <div class="dash-loading">
            <span class="dash-spinner"></span>
            <p>Loading your session summary…</p>
        </div>`;

    let data;
    try {
        const res = await fetch(`${API_BASE_URL}/session/${sessionId}/summary`);
        if (res.status === 404) {
            container.innerHTML = renderEmpty();
            return;
        }
        if (!res.ok) throw new Error(`Server error ${res.status}`);
        data = await res.json();
    } catch (err) {
        container.innerHTML = `
            <div class="dash-error">
                <span>⚠️</span>
                <p>Could not load dashboard: ${esc(err.message)}</p>
                <button onclick="window._refreshDashboard()">Retry</button>
            </div>`;
        return;
    }

    _lastData = data;
    _searchTerm = '';
    renderAndBind(container, data);
}

function renderEmpty() {
    return `
        <div class="dash-empty">
            <div class="dash-empty-icon">📋</div>
            <h2>${esc(t('dashboard.empty_title'))}</h2>
            <p>${esc(t('dashboard.empty_subtitle'))}</p>
        </div>`;
}

function renderAndBind(container, data) {
    container.innerHTML = renderDashboard(data);
    bindInteractions(container);
}

function renderDashboard(data) {
    const {
        total_checked,
        eligible_count,
        needs_more_info_count,
        eligible_schemes,
        missing_fields,
        category_breakdown,
    } = data;

    const knownCount = PROFILE_FIELD_COUNT - (missing_fields ? missing_fields.length : 0);
    const completenessPct = Math.round((knownCount / PROFILE_FIELD_COUNT) * 100);

    const term = _searchTerm.trim().toLowerCase();
    const visibleSchemes = term
        ? eligible_schemes.filter(s =>
            (s.name || '').toLowerCase().includes(term) ||
            (s.reason || '').toLowerCase().includes(term))
        : eligible_schemes;

    return `
        <div class="dash-content">

            <!-- ── Header row with refresh ─────────────────── -->
            <section class="dash-section">
                <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
                    <h2 class="dash-section-title" style="margin:0;">Session Overview</h2>
                    <button type="button" id="dash-refresh-btn"
                            title="Refresh dashboard"
                            style="border:1px solid #d0c9bd; background:#fff; border-radius:8px; padding:6px 14px; cursor:pointer; font-size:0.9rem;">
                        ⟳ Refresh
                    </button>
                </div>
                <div class="dash-stats" style="margin-top:12px;">
                    ${statCard(t('dashboard.stat_checked'), total_checked, '🔍', 'neutral')}
                    ${statCard(t('dashboard.stat_eligible'), eligible_count, '✅', 'positive')}
                    ${statCard(t('dashboard.stat_need_info'), needs_more_info_count, '⏳', 'warn')}
                </div>
            </section>

            <!-- ── Profile completeness meter ──────────────── -->
            <section class="dash-section">
                <h2 class="dash-section-title">Profile Completeness</h2>
                <div style="display:flex; align-items:center; gap:14px;">
                    <div style="flex:1; height:14px; background:#eee6d8; border-radius:7px; overflow:hidden;">
                        <div style="height:100%; width:${completenessPct}%; border-radius:7px;
                                    background:${completenessPct === 100 ? '#1F6F5C' : '#E08A2C'};
                                    transition: width 600ms ease;"></div>
                    </div>
                    <strong style="white-space:nowrap;">${knownCount} / ${PROFILE_FIELD_COUNT} details</strong>
                </div>
                ${completenessPct < 100
            ? `<p class="dash-hint" style="margin-top:8px;">${esc(t('dashboard.missing_hint'))}</p>`
            : ''}
            </section>

            <!-- ── Eligible scheme cards (searchable) ──────── -->
            <section class="dash-section">
                <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;">
                    <h2 class="dash-section-title" style="margin:0;">Eligible Schemes</h2>
                    ${eligible_schemes.length > 1 ? `
                    <input type="search" id="dash-scheme-search" placeholder="Search schemes…"
                           value="${esc(_searchTerm)}"
                           style="border:1px solid #d0c9bd; border-radius:8px; padding:7px 12px; min-width:200px; font-size:0.9rem;" />
                    ` : ''}
                </div>
                <div style="margin-top:12px;">
                ${eligible_schemes.length === 0
            ? `<p class="dash-hint">${esc(t('dashboard.no_eligible'))}</p>`
            : visibleSchemes.length === 0
                ? `<p class="dash-hint">No schemes match "${esc(_searchTerm)}".</p>`
                : `<div class="dash-scheme-grid">${visibleSchemes.map(schemeCard).join('')}</div>`
        }
                </div>
            </section>

            <!-- ── Category breakdown chart ───────────────── -->
            ${Object.keys(category_breakdown || {}).length > 0 ? `
            <section class="dash-section">
                <h2 class="dash-section-title">Breakdown by Category</h2>
                ${renderBarChart(category_breakdown)}
            </section>` : ''}

            <!-- ── Missing information (clickable) ─────────── -->
            ${missing_fields.length > 0 ? `
            <section class="dash-section">
                <h2 class="dash-section-title">Missing Information</h2>
                <p class="dash-hint">
                    Tap any detail to answer it in the chat.
                </p>
                <div class="dash-missing-grid">
                    ${missing_fields.map(f => `
                        <button type="button" class="dash-missing-chip" data-field="${esc(f)}"
                                style="cursor:pointer; border:1px dashed #d0a35c; background:#fdf6ea; font:inherit;">
                            <span class="dash-missing-icon">❓</span>
                            <span>${esc(getFieldLabel(f))}</span>
                        </button>`).join('')}
                </div>
            </section>` : `
            <section class="dash-section">
                <div class="dash-complete-badge">
                    <span>✔</span> ${esc(t('dashboard.complete_badge'))}
                </div>
            </section>`}

        </div>`;
}

function statCard(label, value, icon, tone) {
    return `
        <div class="dash-stat dash-stat--${tone}">
            <span class="dash-stat__icon">${icon}</span>
            <span class="dash-stat__value">${esc(value)}</span>
            <span class="dash-stat__label">${esc(label)}</span>
        </div>`;
}

function schemeCard(scheme) {
    const reason = scheme.reason && scheme.reason !== 'undefined'
        ? scheme.reason
        : 'Your profile meets the eligibility criteria for this scheme.';
    const benefit = scheme.benefit_amount && scheme.benefit_amount !== 'undefined'
        ? scheme.benefit_amount
        : '';
    const docs = Array.isArray(scheme.documents_needed) ? scheme.documents_needed : [];
    const link = safeUrl(scheme.apply_link);

    return `
        <div class="dash-scheme-card">
            <div class="dash-scheme-card__header">
                <h3 class="dash-scheme-card__name">${esc(scheme.name)}</h3>
                <span class="dash-scheme-card__stamp">ELIGIBLE</span>
            </div>
            ${benefit ? `<p class="dash-scheme-card__benefit">${esc(benefit)}</p>` : ''}
            <p class="dash-scheme-card__reason">${esc(reason)}</p>
            ${docs.length ? `
            <details style="margin:8px 0;">
                <summary style="cursor:pointer; font-weight:600; font-size:0.9rem;">📄 Documents needed (${docs.length})</summary>
                <ul style="margin:8px 0 0 18px; padding:0; font-size:0.9rem;">
                    ${docs.map(d => `<li>${esc(d)}</li>`).join('')}
                </ul>
            </details>` : ''}
            ${link !== '#' ? `
                <a href="${esc(link)}" target="_blank" rel="noopener noreferrer"
                   class="dash-scheme-card__apply">Apply Now ↗</a>` : ''}
        </div>`;
}

/**
 * Pure-CSS horizontal bar chart for category breakdown, animated on render.
 */
function renderBarChart(breakdown) {
    const entries = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);
    const maxVal = Math.max(...entries.map(e => e[1]), 1);

    const bars = entries.map(([cat, count], i) => {
        const pct = Math.round((count / maxVal) * 100);
        const color = CATEGORY_COLORS[i % CATEGORY_COLORS.length];
        return `
            <div class="dash-bar-row">
                <span class="dash-bar-label">${esc(cat)}</span>
                <div class="dash-bar-track">
                    <div class="dash-bar-fill dash-bar-fill--animate"
                         style="width:0%; background:${color}; transition:width 700ms ease ${i * 90}ms;"
                         data-target-width="${pct}">
                        <span class="dash-bar-value">${esc(count)}</span>
                    </div>
                </div>
            </div>`;
    }).join('');

    return `<div class="dash-bar-chart">${bars}</div>`;
}

/** Wire up all interactive behaviors after each render. */
function bindInteractions(container) {
    // Animate chart bars from 0 to their target widths
    requestAnimationFrame(() => {
        container.querySelectorAll('.dash-bar-fill--animate').forEach(el => {
            el.style.width = el.dataset.targetWidth + '%';
        });
    });

    // Refresh button
    const refreshBtn = container.querySelector('#dash-refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            if (_lastSessionId) refreshDashboard(_lastSessionId);
        });
    }

    // Scheme search — filter locally, keep focus and caret position
    const searchInput = container.querySelector('#dash-scheme-search');
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            _searchTerm = searchInput.value;
            const caret = searchInput.selectionStart;
            renderAndBind(container, _lastData);
            const newInput = container.querySelector('#dash-scheme-search');
            if (newInput) {
                newInput.focus();
                newInput.setSelectionRange(caret, caret);
            }
        });
    }

    // Missing-info chips → jump to chat with a starter message
    container.querySelectorAll('.dash-missing-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const field = chip.dataset.field;
            const starter = FIELD_PROMPTS[field] || '';

            // Switch to the Chat tab (reuses the app's own tab handler)
            const tabChat = document.getElementById('tab-chat');
            if (tabChat) tabChat.click();

            // Pre-fill the chat input and focus it, caret at the end
            const input = document.getElementById('chat-input');
            if (input) {
                input.value = starter;
                input.focus();
                input.setSelectionRange(input.value.length, input.value.length);
                input.dispatchEvent(new Event('input'));  // trigger auto-grow
            }
        });
    });
}