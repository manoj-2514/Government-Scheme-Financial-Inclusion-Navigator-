import { t } from './translations.js';

const chatWindowEl = document.getElementById('chat-window');
const emptyStateEl = document.getElementById('empty-state');

function hideEmptyState() {
    if (emptyStateEl) emptyStateEl.style.display = 'none';
}

function showEmptyState() {
    if (emptyStateEl) emptyStateEl.style.display = '';
}

export function clearChat() {
    // Remove all messages and scheme cards (keep only the empty-state div)
    const children = Array.from(chatWindowEl.children);
    children.forEach(child => {
        if (child !== emptyStateEl) child.remove();
    });
    showEmptyState();
}

const TOOL_LABELS_EN = {
    check_eligibility: 'Checked your eligibility against scheme rules',
    search_schemes_by_criteria: 'Searched schemes matching your criteria',
    get_scheme_details: 'Looked up full scheme details',
    query_knowledge_base: 'Searched the knowledge base for relevant info'
};

const TOOL_TRANSLATION_KEYS = {
    check_eligibility: 'chat.tool_check_eligibility',
    search_schemes_by_criteria: 'chat.tool_search_schemes',
    get_scheme_details: 'chat.tool_scheme_details',
    query_knowledge_base: 'chat.tool_knowledge_base'
};

function getToolLabel(name) {
    const key = TOOL_TRANSLATION_KEYS[name];
    if (key) {
        const translated = t(key);
        if (translated && translated !== key) return translated;
    }
    return TOOL_LABELS_EN[name] || name;
}

export function parseMarkdown(text) {
    if (!text) return '';
    let html = String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // 1. Bold: **text** -> <strong>text</strong>
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // 2. Headers: ### text -> <h3>text</h3>
    html = html.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.*?)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.*?)$/gm, '<h1>$1</h1>');

    // 3. Lists
    const lines = html.split('\n');
    let inList = null; // 'ul', 'ol', or null
    const processedLines = [];

    for (let line of lines) {
        const trimmed = line.trim();
        const isUl = trimmed.startsWith('* ') || trimmed.startsWith('- ');
        const isOl = /^\d+\.\s/.test(trimmed);

        if (isUl) {
            const content = trimmed.substring(2).trim();
            if (inList !== 'ul') {
                if (inList) processedLines.push(`</${inList}>`);
                processedLines.push('<ul>');
                inList = 'ul';
            }
            processedLines.push(`<li>${content}</li>`);
        } else if (isOl) {
            const content = trimmed.replace(/^\d+\.\s/, '').trim();
            if (inList !== 'ol') {
                if (inList) processedLines.push(`</${inList}>`);
                processedLines.push('<ol>');
                inList = 'ol';
            }
            processedLines.push(`<li>${content}</li>`);
        } else {
            if (inList) {
                processedLines.push(`</${inList}>`);
                inList = null;
            }
            processedLines.push(line);
        }
    }
    if (inList) {
        processedLines.push(`</${inList}>`);
    }

    html = processedLines.join('\n');

    // 4. Line breaks
    html = html.split('\n').map(line => {
        const trimmed = line.trim();
        if (trimmed.startsWith('<h') || trimmed.endsWith('</h>') ||
            trimmed.startsWith('<ul') || trimmed.endsWith('</ul>') ||
            trimmed.startsWith('<ol') || trimmed.endsWith('</ol>') ||
            trimmed.startsWith('<li') || trimmed.endsWith('</li>')) {
            return line;
        }
        return line ? line + '<br>' : '';
    }).join('\n');

    return html;
}

/**
 * Attach a small copy-to-clipboard button to an agent message.
 * Shows a brief "✓" confirmation after copying.
 */
function attachCopyButton(el, rawText) {
    // Remove a previous copy button if the message is being re-rendered
    const oldBtn = el.querySelector('.msg-copy-btn');
    if (oldBtn) oldBtn.remove();

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.classList.add('msg-copy-btn');
    btn.title = 'Copy message';
    btn.textContent = '⧉';

    btn.addEventListener('click', async () => {
        const text = String(rawText || '');
        let copied = false;
        try {
            await navigator.clipboard.writeText(text);
            copied = true;
        } catch (e) {
            // Fallback for older browsers / non-secure contexts
            try {
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                copied = document.execCommand('copy');
                ta.remove();
            } catch (e2) {
                copied = false;
            }
        }
        btn.textContent = copied ? '✓' : '⧉';
        if (copied) {
            setTimeout(() => { btn.textContent = '⧉'; }, 1500);
        }
    });

    el.appendChild(btn);
}

export function addMessage(text, sender, options = {}) {
    hideEmptyState();
    const { subtitle, toolsUsed } = options;

    let cleanText = text;
    if (text && typeof text === 'object') {
        console.error("Warning: addMessage received an object instead of a string:", text);
        cleanText = text.response || text.text || text.message || text.content || JSON.stringify(text);
    }

    const el = document.createElement('div');
    el.classList.add('message', sender);

    const mainLine = document.createElement('div');
    mainLine.innerHTML = parseMarkdown(cleanText);
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
        summary.textContent = t('chat.how_i_found_this') || 'How I found this';
        trace.appendChild(summary);
        const list = document.createElement('ul');
        toolsUsed.forEach(tool => {
            const name = typeof tool === 'string' ? tool : (tool && tool.tool);
            if (!name) return;
            const li = document.createElement('li');
            li.textContent = getToolLabel(name);
            list.appendChild(li);
        });
        trace.appendChild(list);
        el.appendChild(trace);
    }

    // Copy button on agent messages (useful for sharing scheme info)
    if (sender === 'agent') {
        attachCopyButton(el, cleanText);
    }

    chatWindowEl.appendChild(el);
    chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
    return el;
}

export function updateMessage(el, text, subtitle) {
    el.innerHTML = '';
    let cleanText = text;
    if (text && typeof text === 'object') {
        console.error("Warning: updateMessage received an object instead of a string:", text);
        cleanText = text.response || text.text || text.message || text.content || JSON.stringify(text);
    }

    const mainLine = document.createElement('div');
    mainLine.innerHTML = parseMarkdown(cleanText);
    el.appendChild(mainLine);
    if (subtitle) {
        const subLine = document.createElement('div');
        subLine.classList.add('message-subtitle');
        subLine.textContent = subtitle;
        el.appendChild(subLine);
    }

    // Restore the copy button if this is an agent message
    if (el.classList.contains('agent')) {
        attachCopyButton(el, cleanText);
    }
}

/* ── Suggestion chips ─────────────────────────────────────────
   Tappable starter prompts shown under the welcome message.
   Clicking a chip fills the chat input (fill-then-edit) so the
   user can add details like their state before sending. */

let chipsEl = null;

/**
 * Render suggestion chips in the chat window.
 * @param {{label: string, text: string}[]} items
 * @param {(text: string) => void} onSelect - called with the starter text
 */
export function showSuggestionChips(items, onSelect) {
    clearSuggestionChips();
    if (!items || !items.length) return;

    chipsEl = document.createElement('div');
    chipsEl.classList.add('suggestion-chips');

    items.forEach(item => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.classList.add('suggestion-chip');
        chip.textContent = item.label;
        chip.addEventListener('click', () => onSelect(item.text));
        chipsEl.appendChild(chip);
    });

    chatWindowEl.appendChild(chipsEl);
    chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
}

export function clearSuggestionChips() {
    if (chipsEl) {
        chipsEl.remove();
        chipsEl = null;
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