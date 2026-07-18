/**
 * Translation utility for UI localization.
 * Loads translations from translations.json and provides a t() function.
 */

import { getSelectedLanguage } from './appState.js';

let translations = null;
let currentLanguage = 'en';

/**
 * Load translations from translations.json
 */
async function loadTranslations() {
    if (translations) return translations;
    
    try {
        const response = await fetch('/translations.json');
        translations = await response.json();
        return translations;
    } catch (error) {
        console.error('Failed to load translations:', error);
        return null;
    }
}

/**
 * Get translated string for a given key path.
 * @param {string} path - Dot-separated path (e.g., 'ui.send_button')
 * @param {string} lang - Language code (optional, falls back to selected language)
 * @returns {string} Translated string or key if not found
 */
export function t(path, lang = null) {
    const targetLang = lang || getSelectedLanguage() || 'en';
    const keys = path.split('.');
    
    if (!translations) {
        console.warn('Translations not loaded yet, returning key:', path);
        return path;
    }
    
    let value = translations[targetLang];
    for (const key of keys) {
        if (value && typeof value === 'object' && key in value) {
            value = value[key];
        } else {
            // Fallback to English if translation not found
            value = translations['en'];
            for (const fallbackKey of keys) {
                if (value && typeof value === 'object' && fallbackKey in value) {
                    value = value[fallbackKey];
                } else {
                    return path; // Return key if not found in English either
                }
            }
            break;
        }
    }
    
    return typeof value === 'string' ? value : path;
}

/**
 * Initialize translations by loading the JSON file
 */
export async function initTranslations() {
    await loadTranslations();
    currentLanguage = getSelectedLanguage() || 'en';
}

/**
 * Update all translatable UI elements when language changes
 */
export function updateUITranslations() {
    const lang = getSelectedLanguage() || 'en';
    
    // Update send button
    const sendBtn = document.querySelector('#chat-form button[type="submit"]');
    if (sendBtn) sendBtn.textContent = t('ui.send_button', lang);
    
    // Update input placeholder
    const chatInput = document.getElementById('chat-input');
    if (chatInput) chatInput.placeholder = t('ui.input_placeholder', lang);
    
    // Update new conversation button
    const newConvBtn = document.getElementById('new-conversation-btn');
    if (newConvBtn) newConvBtn.textContent = t('ui.new_conversation', lang);
    
    // Update passbook label
    const passbookLabel = document.querySelector('.passbook-label');
    if (passbookLabel) passbookLabel.textContent = t('ui.passbook_label', lang);
    
    // Update empty state
    const emptyState = document.getElementById('empty-state');
    if (emptyState) emptyState.textContent = t('ui.empty_state', lang);
    
    // Update tab buttons
    const tabChat = document.getElementById('tab-chat');
    const tabDashboard = document.getElementById('tab-dashboard');
    if (tabChat) tabChat.textContent = t('ui.tab_chat', lang);
    if (tabDashboard) tabDashboard.textContent = t('ui.tab_dashboard', lang);
    
    // Update mic button title
    const micBtn = document.getElementById('mic-btn');
    if (micBtn) micBtn.title = t('ui.mic_button_title', lang);
    
    // Update menu toggle aria-label
    const menuToggle = document.getElementById('menu-toggle');
    if (menuToggle) menuToggle.setAttribute('aria-label', t('ui.menu_toggle', lang));
    
    // Trigger profile re-render with updated labels
    updateProfileTranslations(lang);
}

/**
 * Update profile field labels
 */
function updateProfileTranslations(lang) {
    const profileFields = document.getElementById('profile-fields');
    if (!profileFields) return;
    
    const rows = profileFields.querySelectorAll('div');
    rows.forEach(row => {
        const spans = row.querySelectorAll('span');
        if (spans.length >= 2) {
            const labelText = spans[0].textContent;
            // Map English labels to translation keys
            const labelMap = {
                'Occupation': 'profile.occupation',
                'State': 'profile.state',
                'Land (acres)': 'profile.land_acres',
                'Income': 'profile.income',
                'Age': 'profile.age',
                'Category': 'profile.category',
                'Gender': 'profile.gender'
            };
            const translationKey = labelMap[labelText];
            if (translationKey) {
                spans[0].textContent = t(translationKey, lang);
            }
        }
    });
    
    // Update "still learning" text
    if (profileFields.textContent.includes('Still learning') || 
        profileFields.textContent.includes('अभी भी') ||
        profileFields.textContent.includes('ఇప్పటికీ')) {
        profileFields.textContent = t('profile.still_learning', lang);
    }
}

export { translations };
