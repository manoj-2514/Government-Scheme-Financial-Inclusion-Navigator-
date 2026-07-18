/**
 * Single-screen onboarding: language selection only.
 *
 * The occupation-selection step was removed — the agent discovers the
 * user's occupation naturally through conversation, which keeps the
 * chat, profile, and dashboard consistent.
 */

import {
    setSelectedLanguage,
    markOnboardingComplete,
    isOnboardingComplete,
    getSelectedLanguage,
} from './appState.js';

const LANGUAGES = [
    { code: 'hi', native: 'हिन्दी', accent: '#FF9933' },
    { code: 'te', native: 'తెలుగు', accent: '#F4C430' },
    { code: 'ta', native: 'தமிழ்', accent: '#C0392B' },
    { code: 'kn', native: 'ಕನ್ನಡ', accent: '#F1C40F' },
    { code: 'ml', native: 'മലയാളം', accent: '#27AE60' },
    { code: 'mr', native: 'मराठी', accent: '#E67E22' },
    { code: 'en', native: 'English', accent: '#3B82F6' },
];

function renderBrandHeader() {
    return `
        <div class="onboarding-brand">
            <span class="onboarding-brand__seal">◎</span>
            <h1 class="onboarding-brand__title">Government Scheme &amp; Financial Inclusion Navigator</h1>
            <p class="onboarding-brand__tagline">Find central &amp; state welfare schemes you may be eligible for — explained simply, in your own language.</p>
        </div>
    `;
}

function renderLanguageScreen() {
    const cards = LANGUAGES.map(lang => `
        <button class="onboarding-card onboarding-card--language"
                data-lang="${lang.code}"
                style="--card-accent: ${lang.accent}">
            <div class="onboarding-card__stamp">${lang.code.toUpperCase()}</div>
            <div class="onboarding-card__native">${lang.native}</div>
        </button>
    `).join('');

    return `
        <div class="onboarding-screen">
            ${renderBrandHeader()}
            <div class="onboarding-header">
                <h2 class="onboarding-title">Choose your language</h2>
                <p class="onboarding-subtitle">Select the language you are most comfortable with — you can change it anytime from Settings</p>
            </div>
            <div class="onboarding-grid onboarding-grid--languages">
                ${cards}
            </div>
        </div>
    `;
}

function bindLanguageScreen(root, onComplete, isSettingsMode = false) {
    const currentLanguage = getSelectedLanguage();

    root.querySelectorAll('[data-lang]').forEach(btn => {
        const isActive = btn.dataset.lang === currentLanguage;
        btn.classList.toggle('onboarding-card--selected', isActive);

        btn.addEventListener('click', () => {
            // Brief visual confirmation before transitioning
            root.querySelectorAll('[data-lang]').forEach(b =>
                b.classList.remove('onboarding-card--selected')
            );
            btn.classList.add('onboarding-card--selected');

            setSelectedLanguage(btn.dataset.lang);

            if (!isSettingsMode) {
                markOnboardingComplete();
            }

            // Small delay so the user sees the selection confirm before the screen changes
            setTimeout(() => {
                showMainApp();
                onComplete({ language: btn.dataset.lang });
            }, 180);
        });
    });
}

function showMainApp() {
    document.body.classList.remove('body--onboarding');
    const onboardingEl = document.getElementById('onboarding');
    if (onboardingEl) onboardingEl.classList.add('onboarding--hidden');

    const mainApp = document.getElementById('main-app');
    if (mainApp) mainApp.classList.remove('main-app--hidden');
}

/**
 * Initialize onboarding. If already complete, shows the main app immediately.
 * @param {(choices: { language: string }) => void} onComplete
 * @returns {boolean} whether onboarding was skipped (already complete)
 */
export function initOnboarding(onComplete) {
    const root = document.getElementById('onboarding');
    if (!root) return true;

    if (isOnboardingComplete()) {
        showMainApp();
        onComplete({ language: getSelectedLanguage() });
        return true;
    }

    document.body.classList.add('body--onboarding');
    root.innerHTML = renderLanguageScreen();
    bindLanguageScreen(root, onComplete);
    return false;
}

/**
 * Show the settings screen for changing language.
 * Same screen as onboarding, but doesn't re-mark completion.
 * @param {(choices: { language: string }) => void} onComplete
 */
export function showSettings(onComplete) {
    const root = document.getElementById('onboarding');
    if (!root) {
        console.error('[showSettings] Onboarding root not found');
        return;
    }

    const mainApp = document.getElementById('main-app');
    if (mainApp) mainApp.classList.add('main-app--hidden');

    document.body.classList.add('body--onboarding');
    root.classList.remove('onboarding--hidden');

    root.innerHTML = renderLanguageScreen();
    bindLanguageScreen(root, onComplete, true); // true = settings mode
}