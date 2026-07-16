const chatWindowEl = document.getElementById('chat-window');
const emptyStateEl = document.getElementById('empty-state');

function hideEmptyState() {
    if (emptyStateEl) emptyStateEl.style.display = 'none';
}

const TOOL_LABELS = {
    check_eligibility: 'Checked your eligibility against scheme rules',
    search_schemes_by_criteria: 'Searched schemes matching your criteria',
    get_scheme_details: 'Looked up full scheme details',
    query_knowledge_base: 'Searched the knowledge base for relevant info'
};

export function addMessage(text, sender, options = {}) {
    hideEmptyState();
    const { subtitle, toolsUsed } = options;

    const el = document.createElement('div');
    el.classList.add('message', sender);

    const mainLine = document.createElement('div');
    mainLine.textContent = text;
    el.appendChild(mainLine);

    if (subtitle) {
        const subLine = document.createElement('div');
        subLine.classList.add('message-subtitle');
        subLine.textContent = subtitle;
        el.appendChild(subLine);
    }

    if (toolsUsed && toolsUsed.length) {
        const trace = document.createElement('details');
        trace.classList.add('tools-trace');
        const summary = document.createElement('summary');
        summary.textContent = 'How I found this';
        trace.appendChild(summary);
        const list = document.createElement('ul');
        toolsUsed.forEach(tool => {
            const li = document.createElement('li');
            li.textContent = TOOL_LABELS[tool] || tool;
            list.appendChild(li);
        });
        trace.appendChild(list);
        el.appendChild(trace);
    }

    chatWindowEl.appendChild(el);
    chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
    return el;
}

export function updateMessage(el, text, subtitle) {
    el.innerHTML = '';
    const mainLine = document.createElement('div');
    mainLine.textContent = text;
    el.appendChild(mainLine);
    if (subtitle) {
        const subLine = document.createElement('div');
        subLine.classList.add('message-subtitle');
        subLine.textContent = subtitle;
        el.appendChild(subLine);
    }
}

let typingEl = null;

export function showTyping() {
    hideEmptyState();
    typingEl = document.createElement('div');
    typingEl.classList.add('message', 'agent', 'typing-indicator');
    typingEl.innerHTML = '<span></span><span></span><span></span>';
    chatWindowEl.appendChild(typingEl);
    chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
}

export function hideTyping() {
    if (typingEl) {
        typingEl.remove();
        typingEl = null;
    }
}