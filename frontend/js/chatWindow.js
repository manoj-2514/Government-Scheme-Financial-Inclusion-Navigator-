const chatWindowEl = document.getElementById('chat-window');

export function addMessage(text, sender) {
    const el = document.createElement('div');
    el.classList.add('message', sender); // sender is 'user' or 'agent'
    el.textContent = text;
    chatWindowEl.appendChild(el);
    chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
}

let typingEl = null;

export function showTyping() {
    typingEl = document.createElement('div');
    typingEl.classList.add('message', 'agent');
    typingEl.textContent = '...';
    chatWindowEl.appendChild(typingEl);
    chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
}

export function hideTyping() {
    if (typingEl) {
        typingEl.remove();
        typingEl = null;
    }
}