const profileFieldsEl = document.getElementById('profile-fields');

const FIELD_LABELS = {
    occupation: 'Occupation',
    state: 'State',
    land_acres: 'Land (acres)',
    income: 'Income',
    age: 'Age',
    category: 'Category',
    gender: 'Gender'
};

export function updateProfile(profile) {
    if (!profile) return;

    profileFieldsEl.innerHTML = '';

    Object.entries(profile).forEach(([key, value]) => {
        if (value === null || value === undefined || value === '') return; // hide unknown fields, per the doc
        const label = FIELD_LABELS[key] || key;
        const row = document.createElement('div');
        row.textContent = `${label}: ${value}`;
        profileFieldsEl.appendChild(row);
    });

    if (!profileFieldsEl.children.length) {
        profileFieldsEl.textContent = 'Still learning about you...';
    }
}