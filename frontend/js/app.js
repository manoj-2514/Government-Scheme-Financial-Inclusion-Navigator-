import { addMessage, updateMessage, showTyping, hideTyping } from './chatWindow.js';
import { renderSchemeCards } from './schemeResultCard.js';
import { updateProfile } from './profileSummary.js';
import { initLanguageSelector, initMicButton, getSelectedLanguage } from './voiceInput.js';

const USE_MOCK = true;
const API_BASE_URL = 'http://localhost:8000';

let sessionId = sessionStorage.getItem('session_id');
if (!sessionId) {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem('session_id', sessionId);
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

    const res = await fetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message })
    });
    if (!res.ok) throw new Error(`Server responded with ${res.status}`);
    return res.json();
}

const MOCK_VOICE_BY_LANG = {
    hi: { transcribed_text: "मैं कर्नाटक में 3 एकड़ जमीन वाला किसान हूं", translated_response: "आपने जो साझा किया है, उसके आधार पर आप PM-KISAN के लिए पात्र हो सकते हैं।" },
    te: { transcribed_text: "నేను కర్ణాటకలో 3 ఎకరాల భూమి ఉన్న రైతుని", translated_response: "మీరు పంచుకున్న దాని ఆధారంగా, మీరు PM-KISAN కి అర్హులు కావచ్చు." },
    ta: { transcribed_text: "நான் கர்நாடகாவில் 3 ஏக்கர் நிலம் உள்ள விவசாயி", translated_response: "நீங்கள் பகிர்ந்தவற்றின் அடிப்படையில், நீங்கள் PM-KISAN க்கு தகுதி பெறலாம்." },
    kn: { transcribed_text: "ನಾನು ಕರ್ನಾಟಕದಲ್ಲಿ 3 ಎಕರೆ ಭೂಮಿ ಹೊಂದಿರುವ ರೈತ", translated_response: "ನೀವು ಹಂಚಿಕೊಂಡಿರುವ ಆಧಾರದ ಮೇಲೆ, ನೀವು PM-KISAN ಗೆ ಅರ್ಹರಾಗಿರಬಹುದು." },
    ml: { transcribed_text: "ഞാൻ കർണാടകയിൽ 3 ഏക്കർ ഭൂമിയുള്ള ഒരു കർഷകനാണ്", translated_response: "നിങ്ങൾ പങ്കുവെച്ചതിന്റെ അടിസ്ഥാനത്തിൽ, നിങ്ങൾ PM-KISAN ന് അർഹനായിരിക്കാം." },
    mr: { transcribed_text: "मी कर्नाटकात 3 एकर जमीन असलेला शेतकरी आहे", translated_response: "आपण शेअर केलेल्या माहितीनुसार, आपण PM-KISAN साठी पात्र होऊ शकता." },
    en: { transcribed_text: "I am a farmer with 3 acres of land in Karnataka", translated_response: "Based on what you've shared, you may qualify for PM-KISAN." },
    '': { transcribed_text: "I am a farmer with 3 acres of land in Karnataka", translated_response: "Based on what you've shared, you may qualify for PM-KISAN." }
};

async function sendVoiceMessage(audioBlob) {
    const language = getSelectedLanguage();

    if (USE_MOCK) {
        await new Promise(r => setTimeout(r, 800));
        const mock = MOCK_VOICE_BY_LANG[language] || MOCK_VOICE_BY_LANG[''];
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
    if (!res.ok) throw new Error(`Server responded with ${res.status}`);
    return res.json();
}

async function handleVoiceRecording(audioBlob) {
    const userMsgEl = addMessage('🎙️ Processing voice message...', 'user');
    showTyping();

    try {
        const data = await sendVoiceMessage(audioBlob);
        hideTyping();
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
        addMessage("Sorry, I couldn't process that voice message.", 'agent');
        console.error(err);
    }
}

const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');

chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;

    addMessage(message, 'user');
    chatInput.value = '';
    showTyping();

    try {
        const data = await sendMessage(message);
        hideTyping();
        addMessage(data.response, 'agent', { toolsUsed: data.tools_used });
        updateProfile(data.profile);
        if (data.eligible_schemes) renderSchemeCards(data.eligible_schemes);
    } catch (err) {
        hideTyping();
        addMessage("Sorry, I couldn't reach the server. Is the backend running?", 'agent');
        console.error(err);
    }
});

initLanguageSelector();
initMicButton(handleVoiceRecording);

const menuToggle = document.getElementById('menu-toggle');
const appEl = document.querySelector('.app');
const sidebarOverlay = document.getElementById('sidebar-overlay');

if (menuToggle) menuToggle.addEventListener('click', () => appEl.classList.toggle('sidebar-open'));
if (sidebarOverlay) sidebarOverlay.addEventListener('click', () => appEl.classList.remove('sidebar-open'));