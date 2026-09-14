// Typing suggestions and /report Command Autocomplete for the chat input.
// Filters questions as the user types, supports /report command,
// arrow-key + click selection, and the quick /report action pill.
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('userInput');
    const box = document.getElementById('suggestionsBox');
    if (!input || !box) return;

    // Built-in Slash Commands (exclusively for report generation)
    const SLASH_COMMANDS = [
        {
            cmd: '/report',
            label: '/report <prompt>',
            desc: 'Generate intelligence PDF/HTML report preview from verified database',
            insertText: '/report ',
            icon: '📄'
        }
    ];

    // The full suggestion pool fetched from the backend (reads from the "question" file)
    let SUGGESTIONS = [];

    // Fetch the list from the server
    fetch('/api/suggestions')
        .then(res => res.json())
        .then(data => {
            if (data.suggestions && Array.isArray(data.suggestions)) {
                SUGGESTIONS = data.suggestions;
            }
        })
        .catch(err => console.error('Failed to load suggestions:', err));

    let matches = [];
    let isSlashMode = false;
    let activeIndex = -1;

    const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));

    // Bold the typed portion inside a suggestion.
    function highlight(text, query) {
        const idx = text.toLowerCase().indexOf(query.toLowerCase());
        if (idx === -1 || !query) return escapeHtml(text);
        return escapeHtml(text.slice(0, idx))
            + '<span class="suggestion-match">' + escapeHtml(text.slice(idx, idx + query.length)) + '</span>'
            + escapeHtml(text.slice(idx + query.length));
    }

    function hide() {
        box.hidden = true;
        box.innerHTML = '';
        matches = [];
        isSlashMode = false;
        activeIndex = -1;
    }

    function render(query) {
        const trimmed = query.trim();
        const q = trimmed.toLowerCase();
        // No text yet -> no suggestions (avoids covering the screen on focus).
        if (!q) { hide(); return; }

        // ── Slash Command Autocomplete Mode (Only for /report) ─────────────
        if (q.startsWith('/')) {
            isSlashMode = true;
            const cmdQuery = q.split(' ')[0]; // match the command part
            matches = SLASH_COMMANDS.filter(c => 
                c.cmd.startsWith(cmdQuery) || c.label.toLowerCase().includes(q)
            );

            if (matches.length === 0) { hide(); return; }

            activeIndex = -1;
            box.innerHTML = matches.map((item, i) => `
                <div class="suggestion-item slash-suggestion-item" role="option" data-index="${i}">
                    <span class="slash-item-icon">${item.icon}</span>
                    <div class="slash-item-content">
                        <span class="slash-item-label">${highlight(item.label, cmdQuery)}</span>
                        <span class="slash-item-desc">${escapeHtml(item.desc)}</span>
                    </div>
                </div>
            `).join('');
            box.hidden = false;
            return;
        }

        // ── Standard Natural-Language Suggestions Mode ────────────────────
        isSlashMode = false;
        matches = SUGGESTIONS
            .filter(s => s.toLowerCase().includes(q) && s.toLowerCase() !== q)
            .slice(0, 6);

        if (matches.length === 0) { hide(); return; }

        activeIndex = -1;
        box.innerHTML = matches.map((s, i) => `
            <div class="suggestion-item" role="option" data-index="${i}">
                <svg class="suggestion-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21 21-4.3-4.3"/><circle cx="11" cy="11" r="8"/></svg>
                <span class="suggestion-text">${highlight(s, query.trim())}</span>
            </div>
        `).join('');
        box.hidden = false;
    }

    function setActive(i) {
        const items = box.querySelectorAll('.suggestion-item');
        items.forEach(el => el.classList.remove('active'));
        if (i >= 0 && i < items.length) {
            items[i].classList.add('active');
            items[i].scrollIntoView({ block: 'nearest' });
        }
        activeIndex = i;
    }

    function choose(itemOrText) {
        let textToInsert = typeof itemOrText === 'object' && itemOrText !== null ? itemOrText.insertText : itemOrText;
        input.value = textToInsert;
        hide();
        input.focus();
        // Trigger the app's existing input handler (toggles the send button, resizes).
        input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    // Filter as the user types (runs alongside script.js's own input listener).
    input.addEventListener('input', () => render(input.value));

    // Keyboard handling in the CAPTURE phase so we can intercept Enter/Arrows
    // before script.js's send handler runs — but only when the dropdown is open.
    input.addEventListener('keydown', (e) => {
        if (box.hidden || matches.length === 0) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            e.stopImmediatePropagation();
            setActive((activeIndex + 1) % matches.length);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            e.stopImmediatePropagation();
            setActive((activeIndex - 1 + matches.length) % matches.length);
        } else if (e.key === 'Enter') {
            // Only capture Enter if a suggestion is highlighted; otherwise let it send.
            if (activeIndex >= 0) {
                e.preventDefault();
                e.stopImmediatePropagation();
                choose(matches[activeIndex]);
            } else {
                hide();
            }
        } else if (e.key === 'Escape') {
            e.stopImmediatePropagation();
            hide();
        }
    }, true);

    // Click / hover selection.
    box.addEventListener('mousedown', (e) => {
        // mousedown (not click) so it fires before the input loses focus.
        const item = e.target.closest('.suggestion-item');
        if (!item) return;
        e.preventDefault();
        choose(matches[Number(item.dataset.index)]);
    });
    box.addEventListener('mousemove', (e) => {
        const item = e.target.closest('.suggestion-item');
        if (item) setActive(Number(item.dataset.index));
    });

    // Hide when focus leaves the input area.
    input.addEventListener('blur', () => setTimeout(hide, 120));

    // ── Quick Command Pills Bar Click Handling ─────────────────────────────
    document.querySelectorAll('.quick-cmd-pill').forEach(pill => {
        pill.addEventListener('click', (e) => {
            e.preventDefault();
            const cmd = pill.dataset.cmd;
            if (cmd) {
                input.value = cmd;
                input.focus();
                input.dispatchEvent(new Event('input', { bubbles: true }));
                // Position cursor at end of input
                const len = input.value.length;
                input.setSelectionRange(len, len);
            }
        });
    });
});
