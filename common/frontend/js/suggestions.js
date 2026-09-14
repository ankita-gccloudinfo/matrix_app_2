// Typing suggestions for the chat input.
// Filters a list personalized from the user's own search history as they
// type, supports arrow-key + click selection, and does NOT interfere with
// the existing Enter-to-send handler unless a suggestion is actively
// highlighted.
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('userInput');
    const box = document.getElementById('suggestionsBox');
    if (!input || !box) return;

    // The suggestion pool — personalized from this user's own recent search
    // history (see /api/suggestions/personalized), not the generic static
    // "question" file pool. That endpoint already falls back to a few static
    // suggestions on its own for a brand-new user with no history yet, so
    // this stays sensible either way.
    let SUGGESTIONS = [];

    // Fetch the list from the server
    fetch('/api/suggestions/personalized')
        .then(res => res.json())
        .then(data => {
            if (data.suggestions && Array.isArray(data.suggestions)) {
                SUGGESTIONS = data.suggestions;
            }
        })
        .catch(err => console.error('Failed to load suggestions:', err));

    let matches = [];
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
        activeIndex = -1;
    }

    function render(query) {
        const q = query.trim().toLowerCase();
        // No text yet -> no suggestions (avoids covering the screen on focus).
        if (!q) { hide(); return; }

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

    function choose(text) {
        input.value = text;
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
});
