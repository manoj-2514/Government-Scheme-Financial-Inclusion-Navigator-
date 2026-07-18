/**
 * Central app state for onboarding choices (language only).
 * Persisted in sessionStorage so the choice survives page refresh within a tab.
 *
 * NOTE: Occupation selection was removed from onboarding — the agent now
 * discovers occupation naturally through conversation.
 */

const STORAGE_KEYS = {
    language: 'app_language',
    onboardingComplete: 'onboarding_complete',
};

let language = sessionStorage.getItem(STORAGE_KEYS.language) || '';

// One-time cleanup: remove the old occupation key left over from previous versions
sessionStorage.removeItem('app_occupation');

export function getSelectedLanguage() {
    return language;
}

export function setSelectedLanguage(code) {
    language = code || '';
    if (language) {
        sessionStorage.setItem(STORAGE_KEYS.language, language);
    } else {
        sessionStorage.removeItem(STORAGE_KEYS.language);
    }
}

export function isOnboardingComplete() {
    return sessionStorage.getItem(STORAGE_KEYS.onboardingComplete) === 'true'
        && !!language;
}

export function markOnboardingComplete() {
    sessionStorage.setItem(STORAGE_KEYS.onboardingComplete, 'true');
}

export function resetOnboarding() {
    language = '';
    sessionStorage.removeItem(STORAGE_KEYS.language);
    sessionStorage.removeItem(STORAGE_KEYS.onboardingComplete);
}