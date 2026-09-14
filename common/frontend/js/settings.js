document.addEventListener('DOMContentLoaded', () => {
    const settingsBtn = document.getElementById('settingsBtn');
    const settingsModal = document.getElementById('settingsModal');
    const closeSettingsBtn = document.getElementById('closeSettingsBtn');
    const closeSettingsBtnFooter = document.getElementById('closeSettingsBtnFooter');

    // Language buttons
    const languageBtns = document.querySelectorAll('.language-btn');

    // Theme buttons
    const themeBtns = document.querySelectorAll('.theme-btn');

    // Related Links toggle
    const relatedLinksToggle = document.getElementById('relatedLinksToggle');

    // 2-Way (hands-free) voice chat toggle
    const twoWayChatToggle = document.getElementById('twoWayChatToggle');



    // LiveAvatar API Key override
    const liveAvatarKeyInput = document.getElementById('liveAvatarKeyInput');

    // LiveAvatar Avatar ID override
    const liveAvatarIdInput = document.getElementById('liveAvatarIdInput');

    // Like/Dislike feedback buttons toggle (off by default)
    const likeDislikeToggle = document.getElementById('likeDislikeToggle');

    // Save-to-profile button (syncs current settings to MongoDB via the
    // logged-in user's profile — see auth.js/server.py's /api/settings)
    const saveSettingsBtn = document.getElementById('saveSettingsBtn');
    const settingsSaveStatus = document.getElementById('settingsSaveStatus');

    // ════════════════════════════════════════════════════════════════
    // SETTINGS MODAL - OPEN/CLOSE
    // ════════════════════════════════════════════════════════════════

    function openSettings() {
        settingsModal?.classList.add('active');
        document.body.style.overflow = 'hidden';
        updateSettingsUI();
        renderPdfExpertsSettings();
    }

    function closeSettings() {
        settingsModal?.classList.remove('active');
        document.body.style.overflow = '';
    }

    settingsBtn?.addEventListener('click', openSettings);
    closeSettingsBtn?.addEventListener('click', closeSettings);
    closeSettingsBtnFooter?.addEventListener('click', closeSettings);

    // Close on backdrop click
    settingsModal?.addEventListener('click', (e) => {
        if (e.target === settingsModal) {
            closeSettings();
        }
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && settingsModal?.classList.contains('active')) {
            closeSettings();
        }
    });

    // ════════════════════════════════════════════════════════════════
    // LANGUAGE SWITCHING
    // ════════════════════════════════════════════════════════════════

    languageBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const lang = btn.getAttribute('data-lang');

            // Update i18n
            if (window.i18n) {
                window.i18n.setLanguage(lang);

                // Update UI translations
                window.i18n.updatePageTranslations();
                updateSettingsUI();

                // Update specific dynamic elements
                updateDynamicTranslations();

                // Update lucide icons
                if (window.lucide) {
                    lucide.createIcons();
                }
            }

            // Update active state
            languageBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });

    // ════════════════════════════════════════════════════════════════
    // THEME SWITCHING
    // ════════════════════════════════════════════════════════════════

    themeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const theme = btn.getAttribute('data-theme');

            // Save theme preference
            localStorage.setItem('theme', theme);

            // Apply theme
            applyTheme(theme);

            // Update active state
            themeBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });

    function applyTheme(theme) {
        // All theming is driven by CSS variables keyed on this attribute
        // (see css/variables.css). Setting it switches every var(--…) surface.
        document.documentElement.setAttribute('data-theme', theme);
    }

    // Initialize theme on page load
    const savedTheme = localStorage.getItem('theme') || 'light';
    applyTheme(savedTheme);

    // ════════════════════════════════════════════════════════════════
    // RELATED LINKS TOGGLE
    // ════════════════════════════════════════════════════════════════
    // script.js's loadRelatedLinks() checks window.settingsManager.isRelatedLinksEnabled()
    // before firing, so this toggle alone controls the feature — no other wiring needed.

    relatedLinksToggle?.addEventListener('change', () => {
        localStorage.setItem('relatedLinksEnabled', relatedLinksToggle.checked ? 'true' : 'false');
    });

    // ════════════════════════════════════════════════════════════════
    // LIKE/DISLIKE FEEDBACK TOGGLE — off by default. script.js's
    // addListenButton() checks window.settingsManager.isLikeDislikeEnabled()
    // before rendering the thumbs up/down buttons on a chat response.
    // ════════════════════════════════════════════════════════════════
    likeDislikeToggle?.addEventListener('change', () => {
        localStorage.setItem('likeDislikeEnabled', likeDislikeToggle.checked ? 'true' : 'false');
    });

    // ════════════════════════════════════════════════════════════════
    // 2-WAY (HANDS-FREE) VOICE CHAT TOGGLE
    // ════════════════════════════════════════════════════════════════
    // The actual listen/speak/re-listen loop lives in script.js (it owns the
    // mic + speech-recognition state); this toggle just persists the choice
    // and tells script.js to start or stop the loop right away via
    // window.setTwoWayChatEnabled, exposed the same way script.js exposes
    // sendMessage-adjacent hooks to index.html's avatar module.
    //
    // Deliberately NOT auto-started from the persisted value on page load —
    // starting mic capture without a fresh click can be silently blocked by
    // the browser's user-gesture requirement, which would leave the toggle
    // showing "on" while nothing is actually listening.

    twoWayChatToggle?.addEventListener('change', () => {
        localStorage.setItem('twoWayChatEnabled', twoWayChatToggle.checked ? 'true' : 'false');
        if (window.setTwoWayChatEnabled) window.setTwoWayChatEnabled(twoWayChatToggle.checked);
    });

    const voiceEngineSelect = document.getElementById('voiceEngineSelect');
    if (voiceEngineSelect) {
        // Was unconditionally force-overwriting the saved choice back to
        // 'selfhosted' right after reading it — so picking "Browser Native"
        // never actually stuck past a reload. Just read/write the real value.
        const savedEngine = localStorage.getItem('voiceEngine') || 'browser';
        voiceEngineSelect.value = savedEngine;
        voiceEngineSelect.addEventListener('change', () => {
            localStorage.setItem('voiceEngine', voiceEngineSelect.value);
        });
    }



    // ════════════════════════════════════════════════════════════════
    // LIVEAVATAR API KEY OVERRIDE
    // ════════════════════════════════════════════════════════════════
    // Deliberately in-memory only (window.liveAvatarApiKeyOverride, read by
    // the avatar widget module in index.html) — never written to localStorage
    // or a cookie, so it's gone the instant the page refreshes and the
    // server's .env key takes back over. That's the point: a quick way to
    // try a different account's key without touching the server.

    window.liveAvatarApiKeyOverride = '';

    liveAvatarKeyInput?.addEventListener('input', () => {
        window.liveAvatarApiKeyOverride = liveAvatarKeyInput.value.trim();
    });

    // ════════════════════════════════════════════════════════════════
    // LIVEAVATAR AVATAR ID OVERRIDE
    // ════════════════════════════════════════════════════════════════
    // Same in-memory-only pattern as the API key override above — read by
    // startAvatarSession() in index.html, which prefers this over both the
    // server's default AVATAR_ID and any PDF Expert's assigned avatar_id.

    window.liveAvatarIdOverride = '';

    liveAvatarIdInput?.addEventListener('input', () => {
        window.liveAvatarIdOverride = liveAvatarIdInput.value.trim();
    });

    // ════════════════════════════════════════════════════════════════
    // PDF EXPERTS — manage per-subject avatar faces and PDF scope
    // ════════════════════════════════════════════════════════════════
    // The avatar widget (index.html's module script) owns live session state
    // (which expert is active, the current LiveAvatar session); this panel
    // only reads/writes the backend's per-session expert list and tells the
    // widget to re-sync via window.refreshPdfExperts() after any change.

    const pdfExpertsContainer = document.getElementById('settingsPdfExperts');
    const pdfExpertsEmpty = document.getElementById('settingsPdfExpertsEmpty');
    let settingsAvatarCatalog = null;

    async function loadSettingsAvatarCatalog() {
        if (settingsAvatarCatalog) return settingsAvatarCatalog;
        try {
            const headers = window.liveAvatarApiKeyOverride
                ? { 'X-LiveAvatar-Key': window.liveAvatarApiKeyOverride }
                : {};
            const res = await fetch('/api/avatar-catalog', { headers });
            const data = await res.json();
            settingsAvatarCatalog = data?.data?.results || (Array.isArray(data) ? data : []);
        } catch (e) {
            console.error('Failed to load avatar catalog:', e);
            settingsAvatarCatalog = [];
        }
        return settingsAvatarCatalog;
    }

    async function renderPdfExpertsSettings() {
        if (!pdfExpertsContainer) return;

        let experts = [];
        try {
            const res = await fetch('/api/pdf-experts');
            const data = await res.json();
            experts = data.experts || [];
        } catch (e) {
            console.error('Failed to load PDF experts:', e);
        }

        if (!experts.length) {
            pdfExpertsEmpty.hidden = false;
            pdfExpertsContainer.innerHTML = '';
            return;
        }
        pdfExpertsEmpty.hidden = true;

        const catalog = await loadSettingsAvatarCatalog();
        const avatarOptions = catalog.map(a => `<option value="${a.id}">${a.name || a.id}</option>`).join('');

        pdfExpertsContainer.innerHTML = experts.map(expert => `
            <div class="settings-pdf-expert-card" data-expert="${expert.name}">
                <div class="settings-pdf-expert-name">${expert.name}</div>
                <div class="settings-pdf-expert-row">
                    <label>Avatar</label>
                    <select class="pdf-expert-avatar-select">
                        <option value="">Default</option>
                        ${avatarOptions}
                    </select>
                </div>
                <div class="settings-pdf-expert-row">
                    <label>Knowledge</label>
                    <select class="pdf-expert-scope-select">
                        <option value="own">This expert's PDF(s) only</option>
                        <option value="all">All uploaded PDFs</option>
                    </select>
                </div>
            </div>
        `).join('');

        // Reflect current values (built above with generic option lists)
        pdfExpertsContainer.querySelectorAll('.settings-pdf-expert-card').forEach(card => {
            const expert = experts.find(e => e.name === card.dataset.expert);
            if (!expert) return;
            const avatarSelect = card.querySelector('.pdf-expert-avatar-select');
            const scopeSelect = card.querySelector('.pdf-expert-scope-select');
            if (avatarSelect) avatarSelect.value = expert.avatar_id || '';
            if (scopeSelect) scopeSelect.value = expert.scope_mode || 'own';

            avatarSelect?.addEventListener('change', async () => {
                await fetch('/api/pdf-experts/assign-avatar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: expert.name, avatar_id: avatarSelect.value || null })
                });
                if (window.refreshPdfExperts) window.refreshPdfExperts();
            });

            scopeSelect?.addEventListener('change', async () => {
                await fetch('/api/pdf-experts/set-scope-mode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: expert.name, scope_mode: scopeSelect.value })
                });
                if (window.refreshPdfExperts) window.refreshPdfExperts();
            });
        });
    }

    // ════════════════════════════════════════════════════════════════
    // UI UPDATE FUNCTIONS
    // ════════════════════════════════════════════════════════════════

    function updateSettingsUI() {
        const currentLang = window.i18n?.getLanguage() || 'en';
        const currentTheme = localStorage.getItem('theme') || 'light';

        // Update language buttons
        languageBtns.forEach(btn => {
            if (btn.getAttribute('data-lang') === currentLang) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // Update theme buttons
        themeBtns.forEach(btn => {
            if (btn.getAttribute('data-theme') === currentTheme) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // Update related links toggle
        if (relatedLinksToggle) {
            relatedLinksToggle.checked = localStorage.getItem('relatedLinksEnabled') === 'true';
        }

        // Update 2-way chat toggle (visual state only — see the toggle's
        // own change handler for why this doesn't also start the mic loop)
        if (twoWayChatToggle) {
            twoWayChatToggle.checked = localStorage.getItem('twoWayChatEnabled') === 'true';
        }



        // Update like/dislike feedback toggle (off unless explicitly enabled)
        if (likeDislikeToggle) {
            likeDislikeToggle.checked = localStorage.getItem('likeDislikeEnabled') === 'true';
        }
    }

    function updateDynamicTranslations() {
        // Update placeholder text
        const userInput = document.getElementById('userInput');
        if (userInput) {
            const key = userInput.classList.contains('recording-active')
                ? 'listening'
                : 'askSmartSMI';
            if (window.i18n) {
                userInput.placeholder = window.i18n.t(key);
            }
        }

        // Update status texts if they exist
        const statusElements = document.querySelectorAll('[data-i18n]');
        statusElements.forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (window.i18n) {
                el.textContent = window.i18n.t(key);
            }
        });

        // Re-render the rotating district greeting in the new language
        if (typeof window.refreshGreeting === 'function') {
            window.refreshGreeting();
        }
    }

    // 2-Way Chat never survives a refresh — script.js's mic loop always
    // starts inactive (twoWayChatActive defaults false, nothing restores
    // it from storage), so force the toggle back off here too. Otherwise
    // the checkbox would show "on" from last session while the loop it
    // controls is actually off.
    localStorage.setItem('twoWayChatEnabled', 'false');
    // Same for the "speak replies" sub-toggle — starts off every load
    // regardless of what the user picked last session.
    localStorage.setItem('twoWayChatSpeakEnabled', 'false');

    // ════════════════════════════════════════════════════════════════
    // SAVE / SYNC SETTINGS TO PROFILE (MongoDB)
    // Every toggle above already applies instantly + saves to localStorage
    // on change, unchanged from before — this section additionally persists
    // that same snapshot to the logged-in user's MongoDB profile (via
    // server.py's /api/settings), and can pull it back down on login/page
    // load so preferences follow the user across browsers/devices.
    // ════════════════════════════════════════════════════════════════
    const PROFILE_SETTINGS_KEYS = ['theme', 'relatedLinksEnabled', 'likeDislikeEnabled'];
    // twoWayChatEnabled/twoWayChatSpeakEnabled deliberately excluded — those
    // never survive a refresh anyway (forced off just above), so there's
    // nothing meaningful to carry over to another device.

    function collectSettingsSnapshot() {
        const snapshot = {};
        PROFILE_SETTINGS_KEYS.forEach(key => {
            const value = localStorage.getItem(key);
            if (value !== null) snapshot[key] = value;
        });
        snapshot.language = window.i18n?.getLanguage() || 'en';
        return snapshot;
    }

    function applySettingsSnapshot(snapshot) {
        if (!snapshot) return;
        PROFILE_SETTINGS_KEYS.forEach(key => {
            if (snapshot[key] !== undefined) localStorage.setItem(key, snapshot[key]);
        });
        if (snapshot.theme) applyTheme(snapshot.theme);
        if (snapshot.language && window.i18n) {
            window.i18n.setLanguage(snapshot.language);
            window.i18n.updatePageTranslations();
        }
        updateSettingsUI();
    }

    saveSettingsBtn?.addEventListener('click', async () => {
        if (!settingsSaveStatus) return;
        if (!window.authManager?.isLoggedIn()) {
            settingsSaveStatus.textContent = 'Log in first (profile icon) to save settings to your account.';
            settingsSaveStatus.style.color = '#f59e0b';
            return;
        }
        saveSettingsBtn.disabled = true;
        settingsSaveStatus.textContent = 'Saving...';
        settingsSaveStatus.style.color = '';
        try {
            const res = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: collectSettingsSnapshot() })
            });
            if (!res.ok) throw new Error('Save failed');
            settingsSaveStatus.textContent = 'Saved to your profile.';
            settingsSaveStatus.style.color = '#16a34a';
        } catch (e) {
            console.error(e);
            settingsSaveStatus.textContent = 'Could not save. Try again.';
            settingsSaveStatus.style.color = '#dc2626';
        } finally {
            saveSettingsBtn.disabled = false;
            setTimeout(() => { if (settingsSaveStatus) settingsSaveStatus.textContent = ''; }, 4000);
        }
    });

    async function syncSettingsFromProfile() {
        try {
            const res = await fetch('/api/settings');
            const data = await res.json();
            if (data.logged_in && data.settings && Object.keys(data.settings).length) {
                applySettingsSnapshot(data.settings);
            }
        } catch (e) {
            console.error('Failed to sync settings from profile:', e);
        }
    }
    window._syncSettingsFromProfile = syncSettingsFromProfile;

    // Initialize settings UI on load
    updateSettingsUI();
});

// Export for external use
window.settingsManager = {
    open: () => {
        const settingsBtn = document.getElementById('settingsBtn');
        settingsBtn?.click();
    },
    close: () => {
        const settingsModal = document.getElementById('settingsModal');
        settingsModal?.classList.remove('active');
        document.body.style.overflow = '';
    },
    getLanguage: () => window.i18n?.getLanguage() || 'en',
    setLanguage: (lang) => {
        const btn = document.querySelector(`[data-lang="${lang}"]`);
        if (btn) btn.click();
    },
    getTheme: () => localStorage.getItem('theme') || 'light',
    setTheme: (theme) => {
        const btn = document.querySelector(`[data-theme="${theme}"]`);
        if (btn) btn.click();
    },
    isRelatedLinksEnabled: () => localStorage.getItem('relatedLinksEnabled') === 'true',
    isTwoWayChatEnabled: () => localStorage.getItem('twoWayChatEnabled') === 'true',
    // Called by script.js when it has to give up on the hands-free loop on
    // its own (e.g. mic permission denied) — keeps the Settings checkbox
    // honest instead of showing "on" while nothing is actually listening.
    disableTwoWayChat: () => {
        localStorage.setItem('twoWayChatEnabled', 'false');
        const toggle = document.getElementById('twoWayChatToggle');
        if (toggle) toggle.checked = false;
    },

    // Off by default — script.js's addListenButton() checks this before
    // rendering the thumbs up/down buttons on a chat response.
    isLikeDislikeEnabled: () => localStorage.getItem('likeDislikeEnabled') === 'true',
    // Pulls this profile's saved settings from MongoDB and applies them —
    // called by auth.js right after login and on page load if already
    // logged in (cookie persisted from a previous visit).
    syncFromProfile: () => window._syncSettingsFromProfile?.()
};
