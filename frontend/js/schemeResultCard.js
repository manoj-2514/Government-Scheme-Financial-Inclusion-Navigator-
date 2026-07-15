const chatWindowEl = document.getElementById('chat-window');

export function renderSchemeCards(schemes) {
    if (!schemes || !schemes.length) return;

    const container = document.createElement('div');
    container.classList.add('scheme-cards');

    schemes.forEach(scheme => {
        const card = document.createElement('div');
        card.classList.add('scheme-card');
        card.innerHTML = `
      <div class="scheme-card__stamp">ELIGIBLE</div>
      <h3 class="scheme-card__name">${scheme.name}</h3>
      <div class="scheme-card__benefit">${scheme.benefit_amount}</div>
      <p class="scheme-card__reason">${scheme.reason}</p>
      <div class="scheme-card__docs">
        <span class="scheme-card__docs-label">Documents needed</span>
        <ul>${(scheme.documents_needed || []).map(doc => `<li>${doc}</li>`).join('')}</ul>
      </div>
      <a class="scheme-card__apply" href="${scheme.apply_link}" target="_blank" rel="noopener noreferrer">Apply now →</a>
    `;
        container.appendChild(card);
    });

    chatWindowEl.appendChild(container);
    chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
}