// Project Config Admin — vanilla JS, no build step, same style as the rest
// of this codebase's frontends.
(() => {
    const authScreen = document.getElementById('authScreen');
    const appScreen = document.getElementById('appScreen');
    const authForm = document.getElementById('authForm');
    const authTitle = document.getElementById('authTitle');
    const authSubtitle = document.getElementById('authSubtitle');
    const authSubmitLabel = document.getElementById('authSubmitLabel');
    const authError = document.getElementById('authError');
    const authUsername = document.getElementById('authUsername');
    const authPassword = document.getElementById('authPassword');
    const whoami = document.getElementById('whoami');
    const logoutBtn = document.getElementById('logoutBtn');
    const projectNav = document.getElementById('projectNav');
    const navProjectList = document.getElementById('navProjectList');
    const projectConfigView = document.getElementById('projectConfigView');
    const vmMonitorNavBtn = document.getElementById('vmMonitorNavBtn');
    const vmMonitorView = document.getElementById('vmMonitorView');
    const vmMonitorStatusPill = document.getElementById('vmMonitorStatusPill');
    const vmMonitorRefreshBtn = document.getElementById('vmMonitorRefreshBtn');
    const vmMonitorOpenBtn = document.getElementById('vmMonitorOpenBtn');
    const vmMonitorOffline = document.getElementById('vmMonitorOffline');
    const vmMonitorErrorDetail = document.getElementById('vmMonitorErrorDetail');
    const vmMonitorFrame = document.getElementById('vmMonitorFrame');
    const configTitle = document.getElementById('configTitle');
    const configPort = document.getElementById('configPort');
    const configUpdatedAt = document.getElementById('configUpdatedAt');
    const configRows = document.getElementById('configRows');
    const newKeyInput = document.getElementById('newKeyInput');
    const newValueInput = document.getElementById('newValueInput');
    const addKeyBtn = document.getElementById('addKeyBtn');
    const saveConfigBtn = document.getElementById('saveConfigBtn');
    const saveStatus = document.getElementById('saveStatus');
    const suggestedKeys = document.getElementById('suggestedKeys');
    const createProjectOverlay = document.getElementById('createProjectOverlay');
    const createProjectForm = document.getElementById('createProjectForm');
    const newProjectName = document.getElementById('newProjectName');
    const newProjectLabel = document.getElementById('newProjectLabel');
    const createProjectError = document.getElementById('createProjectError');
    const cancelCreateProjectBtn = document.getElementById('cancelCreateProjectBtn');

    // New Project chooser (Demo vs Chatbot)
    const newProjectChooserOverlay = document.getElementById('newProjectChooserOverlay');
    const chooseDemoBtn = document.getElementById('chooseDemoBtn');
    const chooseChatbotBtn = document.getElementById('chooseChatbotBtn');
    const cancelChooserBtn = document.getElementById('cancelChooserBtn');

    // Demo builder
    const demoBuilderOverlay = document.getElementById('demoBuilderOverlay');
    const demoBuilderForm = document.getElementById('demoBuilderForm');
    const demoName = document.getElementById('demoName');
    const demoTheme = document.getElementById('demoTheme');
    const demoPageCount = document.getElementById('demoPageCount');
    const demoPagesContainer = document.getElementById('demoPagesContainer');
    const demoPdfInput = document.getElementById('demoPdfInput');
    const analyzePdfBtn = document.getElementById('analyzePdfBtn');
    const demoPdfStatus = document.getElementById('demoPdfStatus');
    const demoBuilderError = document.getElementById('demoBuilderError');
    const generateDemoBtn = document.getElementById('generateDemoBtn');
    const demoPreviewEmpty = document.getElementById('demoPreviewEmpty');
    const demoPreviewTabs = document.getElementById('demoPreviewTabs');
    const demoPreviewFrame = document.getElementById('demoPreviewFrame');
    const demoPromoteRow = document.getElementById('demoPromoteRow');
    const backFromDemoBtn = document.getElementById('backFromDemoBtn');
    const regenerateDemoBtn = document.getElementById('regenerateDemoBtn');
    const promoteDemoBtn = document.getElementById('promoteDemoBtn');
    const cancelDemoBtn = document.getElementById('cancelDemoBtn');
    let currentDemoId = null;
    let currentDemoPages = []; // [{slug, name, html}]

    // Delete Project Modal
    const deleteProjectBtn = document.getElementById('deleteProjectBtn');
    const deleteProjectOverlay = document.getElementById('deleteProjectOverlay');
    const deleteProjectMsg = document.getElementById('deleteProjectMsg');
    const deleteProjectPassword = document.getElementById('deleteProjectPassword');
    const deleteProjectError = document.getElementById('deleteProjectError');
    const deleteProjectCancelBtn = document.getElementById('deleteProjectCancelBtn');
    const deleteProjectConfirmBtn = document.getElementById('deleteProjectConfirmBtn');

    // Log Modal
    const viewLogsBtn = document.getElementById('viewLogsBtn');
    const logOverlay = document.getElementById('logOverlay');
    const closeLogBtn = document.getElementById('closeLogBtn');
    const downloadLogBtn = document.getElementById('downloadLogBtn');
    const logContent = document.getElementById('logContent');
    const logTitle = document.getElementById('logTitle');
    let logPollInterval = null;

    // Reference Modal
    const viewReferenceBtn = document.getElementById('viewReferenceBtn');
    const referenceOverlay = document.getElementById('referenceOverlay');
    const referenceCard = document.getElementById('referenceCard');
    const referenceHeader = document.getElementById('referenceHeader');
    const closeReferenceBtn = document.getElementById('closeReferenceBtn');
    const referenceContent = document.getElementById('referenceContent');

    const restartProjectBtn = document.getElementById('restartProjectBtn');
    const openProjectBtn = document.getElementById('openProjectBtn');

    let isBootstrapMode = false;
    let projects = [];
    let activeProjectId = null;
    let currentView = 'project'; // 'project' | 'vm-monitor'
    let currentEnv = {}; // key -> value, the in-progress edit state for the active project
    let revealedKeys = new Set(); // keys currently shown in plain text this render

    // Keys whose values are masked by default (password-style input) until
    // clicked to reveal — purely a UI convenience, the backend has no
    // concept of "sensitive" keys, it stores/returns everything as-is.
    const SENSITIVE_PATTERN = /password|secret|token|api_key|_key$/i;

    // Common config keys across the apps, to make discovery easier — purely
    // a UI convenience (the datalist), the backend accepts any key.
    const SUGGESTED_KEYS = [
        'LLM_BACKEND', 'VLLM_BASE_URL', 'VLLM_MODEL_NAME', 'VLLM_API_KEY',
        'OLLAMA_URL', 'OLLAMA_MODEL_NAME',
        'PDF_QDRANT_HOST', 'PDF_QDRANT_PORT', 'PDF_COLLECTION',
        'LIVEAVATAR_API_KEY', 'AVATAR_ID',
        'MONGO_URI', 'MONGO_DB_NAME',
        'MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DB',
        'QDRANT_HOST', 'QDRANT_PORT', 'QDRANT_COLLECTION',
        'NEO4J_URI', 'NEO4J_USER', 'NEO4J_PASSWORD',
        'EMBED_API_URL', 'EMBEDDING_MODEL',
        'PORT',
    ];
    suggestedKeys.innerHTML = SUGGESTED_KEYS.map(k => `<option value="${k}">`).join('');

    function showAuthError(msg) {
        authError.textContent = msg;
        authError.style.display = 'block';
    }

    async function api(path, options = {}) {
        const res = await fetch(path, {
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        let data = null;
        try { data = await res.json(); } catch (_) { /* no body */ }
        if (!res.ok) {
            throw new Error((data && data.detail) || `Request failed (${res.status})`);
        }
        return data;
    }

    // ── Auth / bootstrap ─────────────────────────────────────────────
    async function initAuth() {
        const { needed } = await api('/api/admin/bootstrap-needed');
        isBootstrapMode = needed;
        if (needed) {
            authTitle.textContent = 'Create Admin Account';
            authSubtitle.textContent = 'No admin account exists yet — create the first (and only) one.';
            authSubmitLabel.textContent = 'Create account';
        } else {
            authTitle.textContent = 'Admin Login';
            authSubtitle.textContent = 'Sign in to manage project configuration.';
            authSubmitLabel.textContent = 'Sign in';
        }
    }

    authForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        authError.style.display = 'none';
        const username = authUsername.value.trim();
        const password = authPassword.value;
        try {
            if (isBootstrapMode) {
                await api('/api/admin/register', { method: 'POST', body: JSON.stringify({ username, password }) });
            }
            const data = await api('/api/admin/login', { method: 'POST', body: JSON.stringify({ username, password }) });
            enterApp(data.username);
        } catch (err) {
            showAuthError(err.message);
        }
    });

    logoutBtn.addEventListener('click', async () => {
        await api('/api/admin/logout', { method: 'POST' });
        location.reload();
    });

    // ── App shell ────────────────────────────────────────────────────
    async function enterApp(username) {
        authScreen.style.display = 'none';
        appScreen.style.display = 'block';
        whoami.textContent = username;

        const data = await api('/api/projects');
        projects = data.projects;
        renderProjectNav();
        if (projects.length) selectProject(projects[0].id);
    }

    function renderProjectNav() {
        navProjectList.innerHTML = '';
        projects.forEach(p => {
            const btn = document.createElement('button');
            btn.dataset.id = p.id;
            btn.className = (currentView === 'project' && p.id === activeProjectId) ? 'active' : '';
            btn.innerHTML = `<span>${escapeHtml(p.label)}</span><span class="port-tag">${p.port}</span>`;
            btn.addEventListener('click', () => selectProject(p.id));
            navProjectList.appendChild(btn);
        });

        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'add-project-btn';
        addBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg> Add Project';
        addBtn.addEventListener('click', openNewProjectChooser);
        navProjectList.appendChild(addBtn);

        vmMonitorNavBtn.classList.toggle('active', currentView === 'vm-monitor');
    }

    // ── New Project chooser (Demo vs Chatbot) ──────────────────────────
    function openNewProjectChooser() {
        newProjectChooserOverlay.style.display = 'flex';
    }

    function closeNewProjectChooser() {
        newProjectChooserOverlay.style.display = 'none';
    }

    chooseChatbotBtn.addEventListener('click', () => {
        closeNewProjectChooser();
        openCreateProjectModal();
    });
    chooseDemoBtn.addEventListener('click', () => {
        closeNewProjectChooser();
        openDemoBuilder();
    });
    cancelChooserBtn.addEventListener('click', closeNewProjectChooser);
    newProjectChooserOverlay.addEventListener('click', (e) => {
        if (e.target === newProjectChooserOverlay) closeNewProjectChooser();
    });

    // ── Create project (Chatbot path) ──────────────────────────────────
    function openCreateProjectModal() {
        newProjectName.value = '';
        newProjectLabel.value = '';
        createProjectError.style.display = 'none';
        createProjectOverlay.style.display = 'flex';
        newProjectName.focus();
    }

    function closeCreateProjectModal() {
        createProjectOverlay.style.display = 'none';
    }

    cancelCreateProjectBtn.addEventListener('click', () => {
        closeCreateProjectModal();
        openNewProjectChooser();
    });
    createProjectOverlay.addEventListener('click', (e) => {
        if (e.target === createProjectOverlay) closeCreateProjectModal();
    });

    createProjectForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        createProjectError.style.display = 'none';
        const name = newProjectName.value.trim();
        const label = newProjectLabel.value.trim();
        try {
            const data = await api('/api/projects', {
                method: 'POST',
                body: JSON.stringify({ name, label: label || undefined }),
            });
            closeCreateProjectModal();
            const projData = await api('/api/projects');
            projects = projData.projects;
            selectProject(data.project.id);
        } catch (err) {
            createProjectError.textContent = err.message;
            createProjectError.style.display = 'block';
        }
    });

    // ── Demo builder (Demo path) ────────────────────────────────────────
    function toSlug(text) {
        return text.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'page';
    }

    function linesToList(text) {
        return (text || '').split('\n').map(s => s.trim()).filter(Boolean);
    }

    // presets: optional array of {name, features[], sample_questions[]} — used when
    // fields are auto-filled from a PDF analysis instead of the built-in placeholders.
    function renderPageFields(presets) {
        const count = parseInt(demoPageCount.value, 10);
        demoPagesContainer.innerHTML = '';
        const defaultNames = ['Public Portal', 'Officer Portal', 'Admin Portal'];
        const defaultFeatures = [
            'Information lookup\nDocument download\nStatus check',
            'Case management\nAnalytics dashboard\nReport generation',
            'User management\nSystem configuration\nAudit logs',
        ];
        for (let i = 0; i < count; i++) {
            const preset = presets && presets[i];
            const nameVal = preset ? preset.name : (defaultNames[i] || '');
            const featuresVal = preset ? (preset.features || []).join('\n') : (defaultFeatures[i] || '');
            const questionsVal = preset ? (preset.sample_questions || []).join('\n') : '';

            const section = document.createElement('div');
            section.className = 'page-section';
            section.innerHTML = `
                <div class="page-section-title">Page ${i + 1}</div>
                <label>
                    Page name
                    <input type="text" class="page-name-input" value="${escapeHtml(nameVal)}" placeholder="e.g. Public Portal">
                </label>
                <label>
                    Features <span>(one per line)</span>
                    <textarea class="page-features-input" rows="3">${escapeHtml(featuresVal)}</textarea>
                </label>
                <label>
                    Sample questions <span>(optional, one per line)</span>
                    <textarea class="page-questions-input" rows="2" placeholder="How do I check my status?&#10;Where can I download the form?">${escapeHtml(questionsVal)}</textarea>
                </label>`;
            demoPagesContainer.appendChild(section);
        }
    }

    function openDemoBuilder() {
        demoBuilderForm.reset();
        demoBuilderError.style.display = 'none';
        demoPdfStatus.style.display = 'none';
        currentDemoId = null;
        currentDemoPages = [];
        renderPageFields();
        showDemoEmptyState();
        demoBuilderOverlay.style.display = 'flex';
        demoName.focus();
    }

    function closeDemoBuilder() {
        demoBuilderOverlay.style.display = 'none';
    }

    function showDemoEmptyState() {
        demoPreviewEmpty.style.display = 'flex';
        demoPreviewEmpty.textContent = 'Preview will show up here.';
        demoPreviewTabs.style.display = 'none';
        demoPreviewFrame.style.display = 'none';
        demoPreviewFrame.srcdoc = '';
        demoPromoteRow.style.display = 'none';
    }

    function showPreviewPage(html, tabEls, activeIdx) {
        demoPreviewFrame.srcdoc = html;
        tabEls.forEach((t, i) => t.classList.toggle('active', i === activeIdx));
    }

    function buildPreviewTabs(mainHtml, pages) {
        demoPreviewTabs.innerHTML = '';
        const allPages = [{ label: 'mainindex', html: mainHtml }, ...pages.map(p => ({ label: p.name, html: p.html }))];
        const tabEls = allPages.map((pg, idx) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = pg.label;
            btn.addEventListener('click', () => showPreviewPage(pg.html, tabEls, idx));
            demoPreviewTabs.appendChild(btn);
            return btn;
        });
        showPreviewPage(mainHtml, tabEls, 0);
        demoPreviewTabs.style.display = 'flex';
    }

    demoPageCount.addEventListener('change', () => renderPageFields());

    function setPdfStatus(msg, kind) {
        demoPdfStatus.textContent = msg;
        demoPdfStatus.style.display = 'block';
        demoPdfStatus.style.color = kind === 'error' ? '#c0392b' : (kind === 'success' ? '#1e824c' : '#666');
    }

    analyzePdfBtn.addEventListener('click', async () => {
        const file = demoPdfInput.files[0];
        if (!file) {
            setPdfStatus('Choose a PDF file first.', 'error');
            return;
        }
        analyzePdfBtn.disabled = true;
        const originalLabel = analyzePdfBtn.textContent;
        analyzePdfBtn.textContent = 'Analyzing…';
        setPdfStatus('Reading document and asking the AI to propose a structure…');
        try {
            const formData = new FormData();
            formData.append('file', file);
            const res = await fetch('/api/demos/analyze-pdf', { method: 'POST', body: formData });
            const data = await res.json().catch(() => null);
            if (!res.ok) {
                throw new Error((data && data.detail) || `Analysis failed (${res.status})`);
            }

            demoName.value = data.name || demoName.value;
            demoTheme.value = data.theme || demoTheme.value;
            const pageCount = Math.min(Math.max((data.pages || []).length, 1), 3);
            demoPageCount.value = String(pageCount);
            renderPageFields(data.pages);

            setPdfStatus(`✓ Auto-filled from "${data.source_filename}" — review the fields below, then click "Generate preview" to accept.`, 'success');
        } catch (err) {
            setPdfStatus(err.message, 'error');
        } finally {
            analyzePdfBtn.disabled = false;
            analyzePdfBtn.textContent = originalLabel;
        }
    });

    async function generateDemo() {
        demoBuilderError.style.display = 'none';
        const name = demoName.value.trim();
        if (!name) return;

        const pageSections = demoPagesContainer.querySelectorAll('.page-section');
        const pages = Array.from(pageSections).map((sec, i) => {
            const pageName = sec.querySelector('.page-name-input').value.trim() || `Page ${i + 1}`;
            return {
                name: pageName,
                slug: toSlug(pageName),
                features: linesToList(sec.querySelector('.page-features-input').value),
                sample_questions: linesToList(sec.querySelector('.page-questions-input').value),
            };
        });

        generateDemoBtn.disabled = true;
        const originalLabel = generateDemoBtn.textContent;
        generateDemoBtn.textContent = 'Starting…';
        demoPreviewEmpty.style.display = 'flex';
        demoPreviewEmpty.textContent = 'Starting…';
        demoPreviewFrame.style.display = 'none';
        demoPreviewTabs.style.display = 'none';

        // Bilingual, 30+-Q&A cards each take tens of seconds to generate, so
        // a 20-30 card demo can run several minutes — the backend streams
        // NDJSON progress lines as each card finishes instead of one long
        // silent wait. See /api/demos/generate in admin_config/server.py.
        try {
            const res = await fetch('/api/demos/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, theme: demoTheme.value.trim(), pages }),
            });
            if (!res.ok) {
                let detail = `Request failed (${res.status})`;
                try { const errData = await res.json(); detail = errData.detail || detail; } catch (e) {}
                throw new Error(detail);
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let finalData = null;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.trim()) continue;
                    const evt = JSON.parse(line);
                    if (evt.type === 'progress') {
                        const label = `Generating ${evt.done}/${evt.total}…`;
                        generateDemoBtn.textContent = label;
                        demoPreviewEmpty.textContent = label;
                    } else if (evt.type === 'error') {
                        throw new Error(evt.detail || 'Generation failed.');
                    } else if (evt.type === 'result') {
                        finalData = evt;
                    }
                }
            }
            if (!finalData) throw new Error('Generation ended without a result.');

            currentDemoId = finalData.demo_id;
            currentDemoPages = finalData.pages || [];
            demoPreviewEmpty.style.display = 'none';
            demoPreviewFrame.style.display = 'block';
            buildPreviewTabs(finalData.html, currentDemoPages);
            demoPromoteRow.style.display = 'flex';
        } catch (err) {
            demoBuilderError.textContent = err.message;
            demoBuilderError.style.display = 'block';
            showDemoEmptyState();
        } finally {
            generateDemoBtn.disabled = false;
            generateDemoBtn.textContent = originalLabel;
        }
    }

    demoBuilderForm.addEventListener('submit', (e) => {
        e.preventDefault();
        generateDemo();
    });
    regenerateDemoBtn.addEventListener('click', generateDemo);

    promoteDemoBtn.addEventListener('click', async () => {
        if (!currentDemoId) return;
        demoBuilderError.style.display = 'none';
        promoteDemoBtn.disabled = true;
        const originalLabel = promoteDemoBtn.textContent;
        promoteDemoBtn.textContent = 'Creating…';
        try {
            const data = await api(`/api/demos/${currentDemoId}/promote`, {
                method: 'POST',
                body: JSON.stringify({}),
            });
            closeDemoBuilder();
            const projData = await api('/api/projects');
            projects = projData.projects;
            selectProject(data.project.id);
        } catch (err) {
            demoBuilderError.textContent = err.message;
            demoBuilderError.style.display = 'block';
        } finally {
            promoteDemoBtn.disabled = false;
            promoteDemoBtn.textContent = originalLabel;
        }
    });

    backFromDemoBtn.addEventListener('click', () => {
        closeDemoBuilder();
        openNewProjectChooser();
    });
    cancelDemoBtn.addEventListener('click', closeDemoBuilder);
    demoBuilderOverlay.addEventListener('click', (e) => {
        if (e.target === demoBuilderOverlay) closeDemoBuilder();
    });

    // ── Delete Project modal ─────────────────────────────────────────────
    function openDeleteModal() {
        const project = projects.find(p => p.id === activeProjectId);
        if (!project) return;
        deleteProjectMsg.textContent = `You are about to remove "${project.label}" from the admin panel. Enter your admin password to confirm.`;
        deleteProjectPassword.value = '';
        deleteProjectError.style.display = 'none';
        deleteProjectOverlay.style.display = 'flex';
        setTimeout(() => deleteProjectPassword.focus(), 50);
    }

    function closeDeleteModal() {
        deleteProjectOverlay.style.display = 'none';
        deleteProjectPassword.value = '';
        deleteProjectError.style.display = 'none';
    }

    deleteProjectBtn.addEventListener('click', openDeleteModal);
    deleteProjectCancelBtn.addEventListener('click', closeDeleteModal);
    deleteProjectOverlay.addEventListener('click', (e) => {
        if (e.target === deleteProjectOverlay) closeDeleteModal();
    });

    deleteProjectConfirmBtn.addEventListener('click', async () => {
        const password = deleteProjectPassword.value;
        if (!password) {
            deleteProjectError.textContent = 'Password is required.';
            deleteProjectError.style.display = 'block';
            return;
        }
        deleteProjectError.style.display = 'none';
        deleteProjectConfirmBtn.disabled = true;
        deleteProjectConfirmBtn.textContent = 'Deleting…';
        try {
            await api(`/api/projects/${activeProjectId}`, {
                method: 'DELETE',
                body: JSON.stringify({ password }),
            });
            closeDeleteModal();
            const projData = await api('/api/projects');
            projects = projData.projects;
            activeProjectId = null;
            renderProjectNav();
            if (projects.length) selectProject(projects[0].id);
        } catch (err) {
            deleteProjectError.textContent = err.message;
            deleteProjectError.style.display = 'block';
        } finally {
            deleteProjectConfirmBtn.disabled = false;
            deleteProjectConfirmBtn.textContent = 'Delete';
        }
    });

    async function selectProject(projectId) {
        currentView = 'project';
        activeProjectId = projectId;
        revealedKeys = new Set();
        vmMonitorView.style.display = 'none';
        projectConfigView.style.display = 'block';
        renderProjectNav();
        const project = projects.find(p => p.id === projectId);
        configTitle.textContent = project ? project.label : projectId;
        configPort.textContent = project ? `port ${project.port}` : '';
        saveStatus.textContent = '';
        saveStatus.className = 'save-status';
        viewLogsBtn.style.display = project ? 'inline-block' : 'none';
        restartProjectBtn.style.display = (project && project.id !== 'admin_config') ? 'inline-block' : 'none';
        openProjectBtn.style.display = project ? 'inline-block' : 'none';
        const protectedIds = ['matrix_app', 'ai_sayak_medical_up', 'river_cannel', 'admin_config'];
        deleteProjectBtn.style.display = (project && !protectedIds.includes(project.id)) ? 'inline-block' : 'none';

        const data = await api(`/api/projects/${projectId}/config`);
        currentEnv = { ...data.env };
        configUpdatedAt.textContent = data.updated_at ? `last saved ${data.updated_at}` : 'never saved';
        renderConfigRows();
    }

    // ── Matrix VM Monitor ────────────────────────────────────────────
    // Embeds the live system-resource dashboard matrix_app/server.py already
    // runs as a subprocess on a fixed port (vm_monitor_service.py) — this
    // just asks the backend which protocol to use and whether it's up right
    // now (see GET /api/vm-monitor/status), then iframes it directly.
    function selectVmMonitor() {
        currentView = 'vm-monitor';
        projectConfigView.style.display = 'none';
        vmMonitorView.style.display = 'flex';
        renderProjectNav();
        loadVmMonitorStatus();
    }

    async function loadVmMonitorStatus() {
        vmMonitorStatusPill.textContent = 'Checking…';
        vmMonitorStatusPill.className = 'status-pill pending';
        vmMonitorOffline.style.display = 'none';
        vmMonitorErrorDetail.textContent = '';
        vmMonitorFrame.style.display = 'none';
        vmMonitorFrame.src = '';

        try {
            const info = await api('/api/vm-monitor/status');
            const url = `${info.protocol}://${location.hostname}:${info.port}/`;
            vmMonitorOpenBtn.onclick = () => window.open(url, '_blank', 'noopener');

            if (info.healthy) {
                vmMonitorStatusPill.textContent = 'Online';
                vmMonitorStatusPill.className = 'status-pill ok';
                vmMonitorFrame.src = url;
                vmMonitorFrame.style.display = 'block';
            } else {
                vmMonitorStatusPill.textContent = 'Offline';
                vmMonitorStatusPill.className = 'status-pill err';
                vmMonitorOffline.style.display = 'block';
            }
        } catch (err) {
            vmMonitorStatusPill.textContent = 'Error';
            vmMonitorStatusPill.className = 'status-pill err';
            vmMonitorOffline.style.display = 'block';
            vmMonitorErrorDetail.textContent = err.message;
        }
    }

    vmMonitorNavBtn.addEventListener('click', selectVmMonitor);
    vmMonitorRefreshBtn.addEventListener('click', loadVmMonitorStatus);

    function renderConfigRows() {
        const keys = Object.keys(currentEnv).sort();
        if (!keys.length) {
            configRows.innerHTML = `<tr class="empty-row"><td colspan="3">No config saved yet for this project — it's using its local .env/hardcoded defaults.</td></tr>`;
            return;
        }
        configRows.innerHTML = keys.map(key => {
            const isSensitive = SENSITIVE_PATTERN.test(key);
            const revealed = revealedKeys.has(key) || !isSensitive;
            return `
            <tr data-key="${escapeHtml(key)}">
                <td class="key-cell">${escapeHtml(key)}</td>
                <td>
                    <div class="value-cell">
                        <input type="${revealed ? 'text' : 'password'}" class="value-input" value="${escapeHtml(currentEnv[key])}">
                        ${isSensitive ? `<button type="button" class="icon-btn reveal-btn" title="${revealed ? 'Hide' : 'Show'} value">${eyeIcon(revealed)}</button>` : ''}
                    </div>
                </td>
                <td class="action-cell">
                    <button type="button" class="icon-btn remove-btn" title="Remove">${trashIcon()}</button>
                </td>
            </tr>`;
        }).join('');

        configRows.querySelectorAll('tr').forEach(row => {
            const key = row.dataset.key;
            row.querySelector('.value-input').addEventListener('input', (e) => {
                currentEnv[key] = e.target.value;
            });
            row.querySelector('.remove-btn').addEventListener('click', () => {
                delete currentEnv[key];
                renderConfigRows();
            });
            const revealBtn = row.querySelector('.reveal-btn');
            if (revealBtn) {
                revealBtn.addEventListener('click', () => {
                    if (revealedKeys.has(key)) revealedKeys.delete(key);
                    else revealedKeys.add(key);
                    renderConfigRows();
                });
            }
        });
    }

    function eyeIcon(open) {
        return open
            ? '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>'
            : '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.9 4.24A10.94 10.94 0 0 1 12 4c6.5 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68M6.61 6.61A13.53 13.53 0 0 0 2 11s3.5 7 10 7a10.96 10.96 0 0 0 5.39-1.61M14.12 14.12a3 3 0 1 1-4.24-4.24"/><path d="m1 1 22 22"/></svg>';
    }

    function trashIcon() {
        return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6h16Z"/></svg>';
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    addKeyBtn.addEventListener('click', () => {
        const key = newKeyInput.value.trim();
        if (!key) return;
        currentEnv[key] = newValueInput.value;
        if (SENSITIVE_PATTERN.test(key)) revealedKeys.add(key); // show it once, right after typing it in
        newKeyInput.value = '';
        newValueInput.value = '';
        renderConfigRows();
        newKeyInput.focus();
    });

    [newKeyInput, newValueInput].forEach(el => {
        el.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); addKeyBtn.click(); }
        });
    });

    saveConfigBtn.addEventListener('click', async () => {
        saveStatus.textContent = 'Saving…';
        saveStatus.className = 'save-status';
        try {
            await api(`/api/projects/${activeProjectId}/config`, {
                method: 'PUT',
                body: JSON.stringify({ env: currentEnv }),
            });
            saveStatus.textContent = 'Saved.';
            saveStatus.className = 'save-status ok';
            const data = await api(`/api/projects/${activeProjectId}/config`);
            configUpdatedAt.textContent = data.updated_at ? `last saved ${data.updated_at}` : '';
        } catch (err) {
            saveStatus.textContent = `Error: ${err.message}`;
            saveStatus.className = 'save-status err';
        }
    });

    restartProjectBtn.addEventListener('click', async () => {
        if (!activeProjectId || activeProjectId === 'admin_config') return;
        
        const originalText = restartProjectBtn.textContent;
        restartProjectBtn.textContent = 'Restarting...';
        restartProjectBtn.disabled = true;
        
        try {
            await api(`/api/projects/${activeProjectId}/restart`, { method: 'POST' });
            saveStatus.textContent = 'Project restarted successfully.';
            saveStatus.className = 'save-status ok';
        } catch (err) {
            saveStatus.textContent = `Restart failed: ${err.message}`;
            saveStatus.className = 'save-status err';
        } finally {
            restartProjectBtn.textContent = originalText;
            restartProjectBtn.disabled = false;
        }
    });

    openProjectBtn.addEventListener('click', () => {
        const project = projects.find(p => p.id === activeProjectId);
        if (!project) return;
        window.open(`${location.protocol}//${location.hostname}:${project.port}/`, '_blank', 'noopener');
    });

    // ── Log Viewer ───────────────────────────────────────────────────
    function openLogModal() {
        if (!activeProjectId) return;
        logTitle.textContent = `Logs: ${activeProjectId}`;
        logContent.textContent = "Loading logs...";
        logOverlay.style.display = 'flex';
        
        fetchLogs();
        logPollInterval = setInterval(fetchLogs, 2000);
    }

    function closeLogModal() {
        logOverlay.style.display = 'none';
        if (logPollInterval) {
            clearInterval(logPollInterval);
            logPollInterval = null;
        }
    }

    async function fetchLogs() {
        try {
            const data = await api(`/api/projects/${activeProjectId}/logs`);
            
            // Auto-scroll logic: only auto-scroll if we are already at the bottom
            const isAtBottom = logContent.scrollHeight - logContent.clientHeight <= logContent.scrollTop + 10;
            
            logContent.textContent = data.logs || "No logs available.";
            
            if (isAtBottom) {
                logContent.scrollTop = logContent.scrollHeight;
            }
        } catch (err) {
            logContent.textContent = `Error fetching logs: ${err.message}`;
        }
    }

    viewLogsBtn.addEventListener('click', openLogModal);
    closeLogBtn.addEventListener('click', closeLogModal);
    downloadLogBtn.addEventListener('click', () => {
        if (!activeProjectId || !logContent.textContent) return;
        const blob = new Blob([logContent.textContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        a.download = `${activeProjectId}_logs_${timestamp}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });
    logOverlay.addEventListener('click', (e) => {
        if (e.target === logOverlay) closeLogModal();
    });

    // ── Draggable modal helper ──────────────────────────────────────
    // Lets a modal card (positioned by the overlay's flex-centering) be
    // picked up by a header element and dragged anywhere on screen.
    // Resizing itself is handled by plain CSS `resize: both` on the card.
    function makeDraggable(cardEl, handleEl) {
        let dragging = false;
        let startX = 0, startY = 0, startLeft = 0, startTop = 0;

        handleEl.addEventListener('mousedown', (e) => {
            if (e.target.closest('button')) return; // don't drag when clicking Close
            dragging = true;
            const rect = cardEl.getBoundingClientRect();
            startLeft = rect.left;
            startTop = rect.top;
            startX = e.clientX;
            startY = e.clientY;
            // Switch from flex-centered to explicitly positioned so it can move freely.
            cardEl.style.position = 'fixed';
            cardEl.style.margin = '0';
            cardEl.style.left = `${startLeft}px`;
            cardEl.style.top = `${startTop}px`;
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!dragging) return;
            const rect = cardEl.getBoundingClientRect();
            let newLeft = startLeft + (e.clientX - startX);
            let newTop = startTop + (e.clientY - startY);
            newLeft = Math.max(0, Math.min(newLeft, window.innerWidth - rect.width));
            newTop = Math.max(0, Math.min(newTop, window.innerHeight - rect.height));
            cardEl.style.left = `${newLeft}px`;
            cardEl.style.top = `${newTop}px`;
        });

        document.addEventListener('mouseup', () => {
            if (!dragging) return;
            dragging = false;
            document.body.style.userSelect = '';
        });
    }

    makeDraggable(referenceCard, referenceHeader);

    // ── Reference Viewer ─────────────────────────────────────────────
    async function openReferenceModal() {
        referenceOverlay.style.display = 'flex';
        referenceContent.textContent = "Loading...";
        try {
            const data = await api('/api/reference/config');
            referenceContent.textContent = data.content;
        } catch (err) {
            referenceContent.textContent = `Error loading reference: ${err.message}`;
        }
    }

    function closeReferenceModal() {
        referenceOverlay.style.display = 'none';
    }

    viewReferenceBtn.addEventListener('click', openReferenceModal);
    closeReferenceBtn.addEventListener('click', closeReferenceModal);
    referenceOverlay.addEventListener('click', (e) => {
        if (e.target === referenceOverlay) closeReferenceModal();
    });

    // ── Boot ─────────────────────────────────────────────────────────
    (async () => {
        const me = await api('/api/admin/me');
        if (me.logged_in) {
            enterApp(me.username);
        } else {
            await initAuth();
            authScreen.style.display = 'flex';
        }
    })();
})();
