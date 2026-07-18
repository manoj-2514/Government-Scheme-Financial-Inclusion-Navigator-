import { t } from './translations.js';

const profileFieldsEl = document.getElementById('profile-fields');

// Internal backend fields that should never be shown to the user
const HIDDEN_FIELDS = new Set(['occupation_locked']);

const FIELD_LABELS = {
    occupation: 'profile.occupation',
    state: 'profile.state',
    land_acres: 'profile.land_acres',
    income: 'profile.income',
    age: 'profile.age',
    category: 'profile.category',
    gender: 'profile.gender'
};

// English fallbacks used if the translation file hasn't loaded or lacks a key,
// so the passbook never shows raw keys like "profile.occupation".
const FALLBACK_LABELS = {
    occupation: 'Occupation',
    state: 'State',
    land_acres: 'Land (acres)',
    income: 'Income',
    age: 'Age',
    category: 'Category',
    gender: 'Gender'
};

function labelFor(key) {
    const translationKey = FIELD_LABELS[key];
    if (translationKey) {
        const translated = t(translationKey);
        // t() returns the key itself when no translation is found — fall back to English
        if (translated && translated !== translationKey) return translated;
        return FALLBACK_LABELS[key] || key;
    }
    return FALLBACK_LABELS[key] || key;
}

function stillLearningText() {
    const text = t('profile.still_learning');
    return text !== 'profile.still_learning' ? text : 'Still learning about you…';
}

export function updateProfile(profile) {
    if (!profile) return;

    profileFieldsEl.innerHTML = '';

    Object.entries(profile).forEach(([key, value]) => {
        if (HIDDEN_FIELDS.has(key)) return;
        if (value === null || value === undefined || value === '') return;

        const row = document.createElement('div');
        const labelSpan = document.createElement('span');
        labelSpan.textContent = labelFor(key);
        const valueSpan = document.createElement('span');
        valueSpan.textContent = String(value);
        row.appendChild(labelSpan);
        row.appendChild(valueSpan);
        profileFieldsEl.appendChild(row);
    });

    if (!profileFieldsEl.children.length) {
        profileFieldsEl.textContent = stillLearningText();
    }
}

export function clearProfile() {
    profileFieldsEl.innerHTML = '';
    profileFieldsEl.textContent = stillLearningText();
}