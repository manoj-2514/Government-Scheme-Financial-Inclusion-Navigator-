import { addMessage, updateMessage, showTyping, hideTyping, clearChat, showSuggestionChips, clearSuggestionChips } from './chatWindow.js';
import { renderSchemeCards } from './schemeResultCard.js';
import { updateProfile, clearProfile } from './profileSummary.js';
import { initLanguageSelector, initMicButton, getSelectedLanguage } from './voiceInput.js';
import { refreshDashboard } from './dashboard.js';
import { initOnboarding, showSettings } from './onboarding.js';
import { initTranslations, updateUITranslations } from './translations.js';

const USE_MOCK = false;
const API_BASE_URL = window.API_BASE_URL || 'http://localhost:8000';

let sessionId = sessionStorage.getItem('session_id');
if (!sessionId) {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem('session_id', sessionId);
}

// Welcome messages no longer mention occupation — the agent discovers it in conversation.
const WELCOME_BY_LANG = {
    en: `Welcome! Tell me about yourself — your occupation, state, income, or age — and I'll find government schemes you qualify for. For example: "I'm a farmer in Karnataka with 2 acres".`,
    hi: `स्वागत है! मुझे अपने बारे में बताएं — आपका व्यवसाय, राज्य, आय या उम्र — और मैं आपके लिए योग्य सरकारी योजनाएँ खोजूंगा। उदाहरण: "मैं कर्नाटक में 2 एकड़ जमीन वाला किसान हूं"।`,
    te: `స్వాగతం! మీ గురించి చెప్పండి — మీ వృత్తి, రాష్ట్రం, ఆదాయం లేదా వయస్సు — మీరు అర్హులైన ప్రభుత్వ పథకాలను నేను కనుగొంటాను. ఉదాహరణ: "నేను కర్ణాటకలో 2 ఎకరాల భూమి ఉన్న రైతుని".`,
    ta: `வரவேற்கிறோம்! உங்களைப் பற்றி சொல்லுங்கள் — உங்கள் தொழில், மாநிலம், வருமானம் அல்லது வயது — நீங்கள் தகுதியுள்ள அரசு திட்டங்களை நான் கண்டுபிடிப்பேன். உதாரணம்: "நான் கர்நாடகாவில் 2 ஏக்கர் நிலம் உள்ள விவசாயி".`,
    kn: `ಸ್ವಾಗತ! ನಿಮ್ಮ ಬಗ್ಗೆ ಹೇಳಿ — ನಿಮ್ಮ ಉದ್ಯೋಗ, ರಾಜ್ಯ, ಆದಾಯ ಅಥವಾ ವಯಸ್ಸು — ನೀವು ಅರ್ಹರಾಗಿರುವ ಸರ್ಕಾರಿ ಯೋಜನೆಗಳನ್ನು ನಾನು ಹುಡುಕುತ್ತೇನೆ. ಉದಾಹರಣೆ: "ನಾನು ಕರ್ನಾಟಕದಲ್ಲಿ 2 ಎಕರೆ ಭೂಮಿ ಹೊಂದಿರುವ ರೈತ".`,
    ml: `സ്വാഗതം! നിങ്ങളെക്കുറിച്ച് പറയൂ — നിങ്ങളുടെ തൊഴിൽ, സംസ്ഥാനം, വരുമാനം അല്ലെങ്കിൽ പ്രായം — നിങ്ങൾ അർഹരായ സർക്കാർ പദ്ധതികൾ ഞാൻ കണ്ടെത്താം. ഉദാഹരണം: "ഞാൻ കർണാടകയിൽ 2 ഏക്കർ ഭൂമിയുള്ള കർഷകനാണ്".`,
    mr: `स्वागत! मला तुमच्याबद्दल सांगा — तुमचा व्यवसाय, राज्य, उत्पन्न किंवा वय — आणि मी तुमच्यासाठी पात्र सरकारी योजना शोधेन. उदाहरण: "मी कर्नाटकात 2 एकर जमीन असलेला शेतकरी आहे".`,
};

let welcomeMsgEl = null;
let hasUserInteracted = false;

// Tappable starter prompts under the welcome message (fill-then-edit:
// clicking fills the input so the user can add details before sending).
const SUGGESTIONS_BY_LANG = {
    en: [
        { label: '🌾 Farmer', text: "I'm a farmer in " },
        { label: '🎓 Student', text: "I'm a student, my age is " },
        { label: '👵 Senior citizen', text: "I'm a senior citizen, my age is " },
        { label: '👷 Worker', text: "I'm a worker in " },
    ],
    hi: [
        { label: '🌾 किसान', text: 'मैं किसान हूं, मेरा राज्य ' },
        { label: '🎓 छात्र', text: 'मैं छात्र हूं, मेरी उम्र ' },
        { label: '👵 वरिष्ठ नागरिक', text: 'मैं वरिष्ठ नागरिक हूं, मेरी उम्र ' },
        { label: '👷 मजदूर', text: 'मैं मजदूर हूं, मेरा राज्य ' },
    ],
    te: [
        { label: '🌾 రైతు', text: 'నేను రైతుని, నా రాష్ట్రం ' },
        { label: '🎓 విద్యార్థి', text: 'నేను విద్యార్థిని, నా వయస్సు ' },
        { label: '👵 వృద్ధులు', text: 'నేను వృద్ధుడిని, నా వయస్సు ' },
        { label: '👷 కార్మికుడు', text: 'నేను కార్మికుడిని, నా రాష్ట్రం ' },
    ],
    ta: [
        { label: '🌾 விவசாயி', text: 'நான் விவசாயி, என் மாநிலம் ' },
        { label: '🎓 மாணவர்', text: 'நான் மாணவர், என் வயது ' },
        { label: '👵 மூத்த குடிமகன்', text: 'நான் மூத்த குடிமகன், என் வயது ' },
        { label: '👷 தொழிலாளி', text: 'நான் தொழிலாளி, என் மாநிலம் ' },
    ],
    kn: [
        { label: '🌾 ರೈತ', text: 'ನಾನು ರೈತ, ನನ್ನ ರಾಜ್ಯ ' },
        { label: '🎓 ವಿದ್ಯಾರ್ಥಿ', text: 'ನಾನು ವಿದ್ಯಾರ್ಥಿ, ನನ್ನ ವಯಸ್ಸು ' },
        { label: '👵 ಹಿರಿಯ ನಾಗರಿಕ', text: 'ನಾನು ಹಿರಿಯ ನಾಗರಿಕ, ನನ್ನ ವಯಸ್ಸು ' },
        { label: '👷 ಕಾರ್ಮಿಕ', text: 'ನಾನು ಕಾರ್ಮಿಕ, ನನ್ನ ರಾಜ್ಯ ' },
    ],
    ml: [
        { label: '🌾 കർഷകൻ', text: 'ഞാൻ കർഷകനാണ്, എന്റെ സംസ്ഥാനം ' },
        { label: '🎓 വിദ്യാർത്ഥി', text: 'ഞാൻ വിദ്യാർത്ഥിയാണ്, എന്റെ പ്രായം ' },
        { label: '👵 മുതിർന്ന പൗരൻ', text: 'ഞാൻ മുതിർന്ന പൗരനാണ്, എന്റെ പ്രായം ' },
        { label: '👷 തൊഴിലാളി', text: 'ഞാൻ തൊഴിലാളിയാണ്, എന്റെ സംസ്ഥാനം ' },
    ],
    mr: [
        { label: '🌾 शेतकरी', text: 'मी शेतकरी आहे, माझे राज्य ' },
        { label: '🎓 विद्यार्थी', text: 'मी विद्यार्थी आहे, माझे वय ' },
        { label: '👵 वरिष्ठ नागरिक', text: 'मी वरिष्ठ नागरिक आहे, माझे वय ' },
        { label: '👷 कामगार', text: 'मी कामगार आहे, माझे राज्य ' },
    ],
};

function renderSuggestionChips(language) {
    const items = SUGGESTIONS_BY_LANG[language] || SUGGESTIONS_BY_LANG.en;
    showSuggestionChips(items, (starterText) => {
        const input = document.getElementById('chat-input');
        if (input) {
            input.value = starterText;
            input.focus();
            input.setSelectionRange(input.value.length, input.value.length);
            input.dispatchEvent(new Event('input'));  // trigger auto-grow
        }
    });
}

function showWelcomeMessage(language) {
    const emptyState = document.getElementById('empty-state');
    if (emptyState) emptyState.remove();

    const welcome = WELCOME_BY_LANG[language] || WELCOME_BY_LANG.en;
    welcomeMsgEl = addMessage(welcome, 'agent');
    renderSuggestionChips(language);
}

// Re-render the welcome message in a new language, but only if the user
// hasn't sent anything yet (never rewrite real conversation history).
function refreshWelcomeLanguage(language) {
    if (hasUserInteracted || !welcomeMsgEl) return;
    const welcome = WELCOME_BY_LANG[language] || WELCOME_BY_LANG.en;
    updateMessage(welcomeMsgEl, welcome);
    renderSuggestionChips(language);
}

/**
 * Hint the browser/OS keyboard about the input language.
 * A website cannot force a keyboard layout, but the `lang` attribute can
 * nudge some mobile keyboards toward the right suggestion language.
 */
function setInputLangHint(language) {
    const input = document.getElementById('chat-input');
    if (input && language) input.setAttribute('lang', language);
}

async function sendMessage(message) {
    if (USE_MOCK) {
        await new Promise(r => setTimeout(r, 600));
        return {
            response: "Thanks! Based on what you've shared, you may qualify for PM-KISAN.",
            profile: { occupation: "farmer", state: "Karnataka", land_acres: 3, income: null, age: null, category: null, gender: null },
            tools_used: ["check_eligibility", "get_scheme_details"],
            eligible_schemes: [
                {
                    name: "PM-KISAN",
                    benefit_amount: "₹6,000/year (3 installments)",
                    reason: "You're a farmer with landholding under the eligible limit in Karnataka.",
                    documents_needed: ["Aadhaar card", "Land ownership papers", "Bank passbook"],
                    apply_link: "https://pmkisan.gov.in"
                }
            ]
        };
    }

    const language = getSelectedLanguage();
    const payload = { session_id: sessionId, message };
    if (language) payload.language = language;

    let res;
    try {
        res = await fetch(`${API_BASE_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    } catch (fetchErr) {
        throw new Error("Could not reach the server. Is the backend server running?");
    }

    if (!res.ok) {
        let errMsg = `Server responded with ${res.status}`;
        try {
            const errData = await res.json();
            if (errData && errData.detail) {
                errMsg = errData.detail;
            }
        } catch (e) {
            // failed to parse JSON error
        }
        throw new Error(errMsg);
    }
    return res.json();
}

async function sendMessageWithRetry(message, retries = 1, delayMs = 1500) {
    try {
        return await sendMessage(message);
    } catch (err) {
        if (retries > 0) {
            console.warn(`Transient chat query error: "${err.message}". Retrying in ${delayMs}ms...`);
            await new Promise(r => setTimeout(r, delayMs));
            return await sendMessageWithRetry(message, retries - 1, delayMs);
        }
        throw err;
    }
}

const MOCK_VOICE_BY_LANG = {
    hi: { transcribed_text: "मैं कर्नाटक में 3 एकड़ जमीन वाला किसान हूं", translated_response: "आपने जो साझा किया है, उसके आधार पर आप PM-KISAN के लिए पात्र हो सकते हैं।" },
    te: { transcribed_text: "నేను కర్ణాటకలో 3 ఎకరాల భూమి ఉన్న రైతుని", translated_response: "మీరు పంచుకున్న దాని ఆధారంగా, మీరు PM-KISAN కి అర్హులు కావచ్చు." },
    ta: { transcribed_text: "நான் கர்நாடகாவில் 3 ஏக்கர் நிலம் உள்ள விவசாயி", translated_response: "நீங்கள் பகிர்ந்தவற்றின் அடிப்படையில், நீங்கள் PM-KISAN க்கு தகுதி பெறலாம்." },
    kn: { transcribed_text: "ನಾನು ಕರ್ನಾಟಕದಲ್ಲಿ 3 ಎಕರೆ ಭೂಮಿ ಹೊಂದಿರುವ ರೈತ", translated_response: "ನೀವು ಹಂಚಿಕೊಂಡಿರುವ ಆಧಾರದ ಮೇಲೆ, ನೀವು PM-KISAN ಗೆ ಅರ್ಹರಾಗಿರಬಹುದು." },
    ml: { transcribed_text: "ഞാൻ കർണാടകയിൽ 3 ഏക്കർ ഭൂമിയുള്ള ഒരു കർഷകനാണ്", translated_response: "നിങ്ങൾ പങ്കുവെച്ചതിന്റെ അടിസ്ഥാനത്തിൽ, നിങ്ങൾ PM-KISAN ന് അർഹനായിരിക്കാം." },
    mr: { transcribed_text: "मी कर्नाटकात 3 एकर जमीन असलेला शेतकरी आहे", translated_response: "आपण शेअर केलेल्या माहितीनुसार, आपण PM-KISAN साठी पात्र होऊ शकता." },
    en: { transcribed_text: "I am a farmer with 3 acres of land in Karnataka", translated_response: "Based on what you've shared, you may qualify for PM-KISAN." },
};

async function sendVoiceMessage(audioBlob) {
    const language = getSelectedLanguage();

    if (USE_MOCK) {
        await new Promise(r => setTimeout(r, 800));
        const mock = MOCK_VOICE_BY_LANG[language] || MOCK_VOICE_BY_LANG.en;
        return {
            transcribed_text: mock.transcribed_text,
            translated_query: "I am a farmer with 3 acres of land in Karnataka",
            agent_response_english: "Based on what you've shared, you may qualify for PM-KISAN.",
            translated_response: mock.translated_response,
            audio_url: null,
            profile: { occupation: "farmer", state: "Karnataka", land_acres: 3, income: null, age: null, category: null, gender: null },
            tools_used: ["check_eligibility"],
            eligible_schemes: [
                {
                    name: "PM-KISAN",
                    benefit_amount: "₹6,000/year (3 installments)",
                    reason: "You're a farmer with landholding under the eligible limit in Karnataka.",
                    documents_needed: ["Aadhaar card", "Land ownership papers", "Bank passbook"],
                    apply_link: "https://pmkisan.gov.in"
                }
            ]
        };
    }

    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');
    formData.append('session_id', sessionId);
    if (language) formData.append('language', language);

    const res = await fetch(`${API_BASE_URL}/voice-query`, { method: 'POST', body: formData });
    if (!res.ok) {
        let errMsg = `Server responded with ${res.status}`;
        try {
            const errData = await res.json();
            if (errData && errData.detail) errMsg = errData.detail;
        } catch (e) { /* non-JSON error body */ }
        throw new Error(errMsg);
    }
    return res.json();
}

const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
let isProcessing = false;

// Textarea auto-grow functionality
function autoGrowTextarea(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
}

// Keyboard handling for Enter/Shift+Enter
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event('submit'));
    } else if (e.key === 'Enter' && e.shiftKey) {
        e.preventDefault();
        const start = chatInput.selectionStart;
        const end = chatInput.selectionEnd;
        const value = chatInput.value;
        chatInput.value = value.substring(0, start) + '\n' + value.substring(end);
        chatInput.selectionStart = chatInput.selectionEnd = start + 1;
        autoGrowTextarea(chatInput);
    }
});

// Auto-grow on input
chatInput.addEventListener('input', () => {
    autoGrowTextarea(chatInput);
});

function setProcessingState(processing) {
    isProcessing = processing;
    const submitBtn = chatForm.querySelector('button[type="submit"]');
    const micBtn = document.getElementById('mic-btn');

    chatInput.disabled = processing;
    if (submitBtn) submitBtn.disabled = processing;
    if (micBtn) micBtn.disabled = processing;
}

async function handleVoiceRecording(audioBlob) {
    if (isProcessing) return;
    hasUserInteracted = true;
    clearSuggestionChips();
    setProcessingState(true);

    const userMsgEl = addMessage('🎙️ Processing voice message...', 'user');
    showTyping();

    try {
        const data = await sendVoiceMessage(audioBlob);
        hideTyping();

        if (data.transcription_failed) {
            updateMessage(userMsgEl, '🎙️ (voice message — understanding failed)');
            addMessage("Sorry, I couldn't understand that clearly — could you try recording again in a quiet place?", 'agent');
            return;
        }

        updateMessage(userMsgEl, data.transcribed_text, data.translated_query);
        addMessage(data.translated_response || data.agent_response_english, 'agent', { toolsUsed: data.tools_used });

        if (data.audio_url) {
            const audio = new Audio(`${API_BASE_URL}${data.audio_url}`);
            audio.play();
        }

        updateProfile(data.profile);
        if (data.eligible_schemes) renderSchemeCards(data.eligible_schemes);
    } catch (err) {
        hideTyping();
        updateMessage(userMsgEl, '🎙️ (voice message — processing failed)');
        addMessage(`Sorry, I couldn't process that voice message. ${err.message || ''}`, 'agent');
        console.error(err);
    } finally {
        setProcessingState(false);
    }
}

function bootstrapMainApp({ language }) {
    initLanguageSelector();
    initMicButton(handleVoiceRecording);

    setInputLangHint(language);
    updateUITranslations();
    showWelcomeMessage(language);

    chatForm.addEventListener('submit', handleChatSubmit);
}

async function handleChatSubmit(e) {
    e.preventDefault();
    if (isProcessing) return;

    const message = chatInput.value.trim();
    if (!message) return;

    hasUserInteracted = true;
    clearSuggestionChips();
    setProcessingState(true);
    addMessage(message, 'user');
    chatInput.value = '';
    chatInput.style.height = 'auto'; // Reset textarea height
    showTyping();

    try {
        const data = await sendMessageWithRetry(message);
        hideTyping();
        addMessage(data.response, 'agent', { toolsUsed: data.tools_used });
        updateProfile(data.profile);
        if (data.eligible_schemes) renderSchemeCards(data.eligible_schemes);
    } catch (err) {
        hideTyping();
        addMessage(`Sorry, an error occurred: ${err.message}`, 'agent');
        console.error(err);
    } finally {
        setProcessingState(false);
    }
}

// ── Startup ───────────────────────────────────────────────
// Load UI translations first so labels never render as raw keys,
// then run onboarding (language picker) and boot the app.
(async () => {
    await initTranslations();
    initOnboarding(({ language }) => {
        bootstrapMainApp({ language });
    });
})();

// Expose dashboard refresh for the retry button rendered in dashboard.js error state
window._refreshDashboard = () => refreshDashboard(sessionId);

// ── Keep the keyboard hint in sync with the quick language buttons ──
const languageSelectorEl = document.getElementById('language-selector');
if (languageSelectorEl) {
    languageSelectorEl.addEventListener('click', (e) => {
        const btn = e.target.closest('.lang-btn');
        if (btn && btn.dataset.lang) {
            setInputLangHint(btn.dataset.lang);
            updateUITranslations();
            refreshWelcomeLanguage(btn.dataset.lang);
        }
    });
}

// ── Tab switching ─────────────────────────────────────────
const tabChat = document.getElementById('tab-chat');
const tabDashboard = document.getElementById('tab-dashboard');
const viewChat = document.getElementById('chat-view');
const viewDashboard = document.getElementById('dashboard-view');

function activateTab(tabName) {
    const isChat = tabName === 'chat';

    tabChat.classList.toggle('tab-btn--active', isChat);
    tabDashboard.classList.toggle('tab-btn--active', !isChat);
    tabChat.setAttribute('aria-selected', isChat);
    tabDashboard.setAttribute('aria-selected', !isChat);

    viewChat.classList.toggle('tab-view--active', isChat);
    viewDashboard.classList.toggle('tab-view--active', !isChat);

    if (!isChat) {
        refreshDashboard(sessionId);
    }
}

if (tabChat) tabChat.addEventListener('click', () => activateTab('chat'));
if (tabDashboard) tabDashboard.addEventListener('click', () => activateTab('dashboard'));

const menuToggle = document.getElementById('menu-toggle');
const appEl = document.querySelector('.app');
const sidebarOverlay = document.getElementById('sidebar-overlay');

if (menuToggle) menuToggle.addEventListener('click', () => appEl.classList.toggle('sidebar-open'));
if (sidebarOverlay) sidebarOverlay.addEventListener('click', () => appEl.classList.remove('sidebar-open'));

function startNewConversation() {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem('session_id', sessionId);

    clearChat();
    clearProfile();
    hasUserInteracted = false;
    showWelcomeMessage(getSelectedLanguage());

    isProcessing = false;
    chatInput.disabled = false;
    const submitBtn = chatForm.querySelector('button[type="submit"]');
    const micBtn = document.getElementById('mic-btn');
    if (submitBtn) submitBtn.disabled = false;
    if (micBtn) micBtn.disabled = false;
    chatInput.focus();

    console.log('[New Conversation] Started with session:', sessionId);
}

const newConversationBtn = document.getElementById('new-conversation-btn');
if (newConversationBtn) newConversationBtn.addEventListener('click', () => {
    startNewConversation();
    activateTab('chat');
    const dashView = document.getElementById('dashboard-view');
    if (dashView) dashView.innerHTML = `
        <div class="dash-empty">
            <div class="dash-empty-icon">📋</div>
            <h2>No session data yet</h2>
            <p>Start a conversation in the Chat tab to see your eligibility summary here.</p>
        </div>`;
});

// Settings button — re-open the language picker
const settingsBtn = document.getElementById('settings-btn');
if (settingsBtn) settingsBtn.addEventListener('click', () => {
    const confirmed = confirm('Change your language? This will update your preference for future messages.');
    if (confirmed) {
        showSettings(({ language }) => {
            setInputLangHint(language);
            updateUITranslations();
            refreshWelcomeLanguage(language);

            // Update language selector highlighting to reflect the new language
            document.querySelectorAll('.lang-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.lang === language);
            });

            console.log('[Settings] Language updated:', language);
        });
    }
});