import { addMessage, showTyping, hideTyping } from './chatWindow.js';
import { renderSchemeCards } from './schemeResultCard.js';
import { updateProfile } from './profileSummary.js';

const USE_MOCK = true;
const API_BASE_URL = 'http://localhost:8000';

// One session_id per browser tab, reused for every message in this conversation
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
} const chatForm = document.getElementById('chat-form');
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
        addMessage(data.response, 'agent');
        updateProfile(data.profile);
        if (data.eligible_schemes) renderSchemeCards(data.eligible_schemes);

        console.log('Tools used:', data.tools_used);
    } catch (err) {
        hideTyping();
        addMessage("Sorry, I couldn't reach the server. Is the backend running?", 'agent');
        console.error(err);
    }
});

