const chatWindowEl = document.getElementById('chat-window');

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

export function renderSchemeCards(schemes) {
  if (!schemes || !schemes.length) return;

  const container = document.createElement('div');
  container.classList.add('scheme-cards');

  schemes.forEach(scheme => {
    const docs = Array.isArray(scheme.documents_needed) ? scheme.documents_needed : [];
    const link = safeUrl(scheme.apply_link);

    const card = document.createElement('div');
    card.classList.add('scheme-card');
    card.innerHTML = `
      <div class="scheme-card__stamp">ELIGIBLE</div>
      <h3 class="scheme-card__name">${esc(scheme.name)}</h3>
      <div class="scheme-card__benefit">${esc(scheme.benefit_amount)}</div>
      <p class="scheme-card__reason">${esc(scheme.reason)}</p>
      ${docs.length ? `
      <div class="scheme-card__docs">
        <span class="scheme-card__docs-label">Documents needed</span>
        <ul>${docs.map(doc => `<li>${esc(doc)}</li>`).join('')}</ul>
      </div>` : ''}
      ${link !== '#' ? `
      <a class="scheme-card__apply" href="${esc(link)}" target="_blank" rel="noopener noreferrer">Apply now →</a>` : ''}
    `;
    container.appendChild(card);
  });

  chatWindowEl.appendChild(container);
  chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
}