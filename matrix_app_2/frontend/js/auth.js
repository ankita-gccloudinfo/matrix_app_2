// Profile / Login — name-only identification (no password) tied to a
// MongoDB user profile (see server.py's /api/auth/* endpoints). Ties chat
// queries to a name for the admin-only query log, and lets Settings sync
// to that profile instead of staying purely local to one browser.
document.addEventListener('DOMContentLoaded', () => {
    const profileBtn = document.getElementById('profileBtn');
    const profileModal = document.getElementById('profileModal');
    const closeProfileBtn = document.getElementById('closeProfileBtn');
    const loggedOutView = document.getElementById('profileLoggedOutView');
    const loggedInView = document.getElementById('profileLoggedInView');
    const nameInput = document.getElementById('profileNameInput');
    const loginBtn = document.getElementById('profileLoginBtn');
    const logoutBtn = document.getElementById('profileLogoutBtn');
    const userAvatar = document.getElementById('profileUserAvatar');
    const userNameEl = document.getElementById('profileUserName');
    const adminBadge = document.getElementById('profileAdminBadge');
    const queryLogLink = document.getElementById('profileQueryLogLink');
    const reportBuilderLink = document.getElementById('profileReportBuilderLink');

    window._currentUser = null; // { name, is_admin } | null

    function renderProfileButton() {
        if (!profileBtn) return;
        profileBtn.textContent = window._currentUser
            ? window._currentUser.name.trim().charAt(0).toUpperCase()
            : '?';
    }

    function renderModalView() {
        const loggedIn = !!window._currentUser;
        if (loggedOutView) loggedOutView.style.display = loggedIn ? 'none' : '';
        if (loggedInView) loggedInView.style.display = loggedIn ? '' : 'none';
        if (!loggedIn) return;

        const initial = window._currentUser.name.trim().charAt(0).toUpperCase();
        if (userAvatar) userAvatar.textContent = initial;
        if (userNameEl) userNameEl.textContent = window._currentUser.name;
        if (adminBadge) adminBadge.style.display = window._currentUser.is_admin ? '' : 'none';
        if (queryLogLink) queryLogLink.style.display = window._currentUser.is_admin ? '' : 'none';
        if (reportBuilderLink) reportBuilderLink.style.display = window._currentUser.is_admin ? '' : 'none';
    }

    // The hero greeting (index.html's <h1 class="greeting">) hardcoded
    // "The mic is yours, Himanshu" regardless of who was actually logged
    // in — or even if no one was. Skipped once index.html's
    // window.refreshGreeting has taken over (location data arrived: "In
    // {district}, you got X posts...") so this doesn't clobber that.
    function updateGreetingIdentity() {
        if (window._greetingData) return;
        const greetingEl = document.querySelector('.greeting');
        if (!greetingEl) return;
        greetingEl.textContent = window._currentUser
            ? `The mic is yours, ${window._currentUser.name}`
            : 'Welcome to AI Matrix';
    }
    window.updateGreetingIdentity = updateGreetingIdentity;

    async function refreshCurrentUser() {
        try {
            const res = await fetch('/api/auth/me');
            const data = await res.json();
            window._currentUser = data.logged_in ? { name: data.name, is_admin: data.is_admin } : null;
        } catch (e) {
            console.error('Failed to check login state:', e);
            window._currentUser = null;
        }
        renderProfileButton();
        renderModalView();
        updateGreetingIdentity();
        // Already logged in from a previous visit (cookie persisted) — pull
        // this profile's saved settings so they carry over on this device too.
        if (window._currentUser && window.settingsManager?.syncFromProfile) {
            await window.settingsManager.syncFromProfile();
        }
    }

    function openProfileModal() {
        profileModal?.classList.add('active');
        document.body.style.overflow = 'hidden';
        renderModalView();
        if (nameInput) nameInput.value = '';
    }

    function closeProfileModal() {
        profileModal?.classList.remove('active');
        document.body.style.overflow = '';
    }

    profileBtn?.addEventListener('click', openProfileModal);
    closeProfileBtn?.addEventListener('click', closeProfileModal);
    profileModal?.addEventListener('click', (e) => {
        if (e.target === profileModal) closeProfileModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && profileModal?.classList.contains('active')) closeProfileModal();
    });

    async function doLogin() {
        const name = (nameInput?.value || '').trim();
        if (!name) return;
        loginBtn.disabled = true;
        loginBtn.textContent = 'Logging in...';
        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            if (!res.ok) throw new Error('Login failed');
            const data = await res.json();
            window._currentUser = { name: data.name, is_admin: data.is_admin };
            renderProfileButton();
            renderModalView();
            updateGreetingIdentity();
            // Pull this profile's saved settings (if any) now that we know who they are.
            if (window.settingsManager?.syncFromProfile) {
                await window.settingsManager.syncFromProfile();
            }
        } catch (e) {
            console.error(e);
            alert('Login failed. Please try again.');
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = 'Login';
        }
    }

    loginBtn?.addEventListener('click', doLogin);
    nameInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doLogin();
    });

    logoutBtn?.addEventListener('click', async () => {
        try {
            await fetch('/api/auth/logout', { method: 'POST' });
        } catch (e) {
            console.error(e);
        }
        window._currentUser = null;
        renderProfileButton();
        renderModalView();
        updateGreetingIdentity();
        closeProfileModal();
    });

    window.authManager = {
        getCurrentUser: () => window._currentUser,
        isLoggedIn: () => !!window._currentUser,
        isAdmin: () => !!window._currentUser?.is_admin,
    };

    refreshCurrentUser();
});
