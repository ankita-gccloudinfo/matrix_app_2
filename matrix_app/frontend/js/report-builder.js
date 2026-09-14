// Standalone Report Builder page — generates a PDF report directly via
// POST /api/reports/generate, bypassing the chat/LLM pipeline entirely.
// This page's own copy of the component-checklist renderer is intentionally
// duplicated from index.html's script.js (_buildReportComponentChecklist)
// rather than shared: script.js is one big DOMContentLoaded closure wired
// to index.html's chat-app DOM/state, so loading it here would pull in a
// whole chat-app bootstrap this page has no use for.
document.addEventListener('DOMContentLoaded', () => {
    const MAX_TOPICS = 15;

    const typeTopicRadio = document.getElementById('rbTypeTopic');
    const typeTrendingRadio = document.getElementById('rbTypeTrending');
    const typeTemplateRadio = document.getElementById('rbTypeTemplate');
    const typeAdhocRadio = document.getElementById('rbTypeAdhoc');
    const builtInSection = document.getElementById('rbBuiltInSection');
    const templateSection = document.getElementById('rbTemplateSection');
    const adhocSection = document.getElementById('rbAdhocSection');
    const topicSection = document.getElementById('rbTopicSection');
    const trendingSection = document.getElementById('rbTrendingSection');
    const topicSearchInput = document.getElementById('rbTopicSearch');
    const districtFilter = document.getElementById('rbDistrictFilter');
    const topicResultsEl = document.getElementById('rbTopicResults');
    const selectedTopicsEl = document.getElementById('rbSelectedTopics');
    const topicCountEl = document.getElementById('rbTopicCount');
    const dateFromInput = document.getElementById('rbDateFrom');
    const dateToInput = document.getElementById('rbDateTo');
    const checklistContainer = document.getElementById('rbChecklistContainer');
    const customInstructionsInput = document.getElementById('rbCustomInstructions');
    const generateBtn = document.getElementById('rbGenerateBtn');
    const resultEl = document.getElementById('rbResult');

    // Adhoc section elements
    const adhocPromptInput = document.getElementById('rbAdhocPrompt');
    const adhocTopicSearchInput = document.getElementById('rbAdhocTopicSearch');
    const adhocTopicResultsEl = document.getElementById('rbAdhocTopicResults');
    const adhocSelectedTopicEl = document.getElementById('rbAdhocSelectedTopic');
    const adhocPreviewBtn = document.getElementById('rbAdhocPreviewBtn');
    const adhocPreviewContainer = document.getElementById('rbAdhocPreviewContainer');
    const adhocPreviewMetaEl = document.getElementById('rbAdhocPreviewMeta');
    const adhocPreviewIframe = document.getElementById('rbAdhocPreviewIframe');
    const adhocExpandBtn = document.getElementById('rbAdhocExpandBtn');
    const adhocConfirmBtn = document.getElementById('rbAdhocConfirmBtn');
    const adhocEditTextarea = document.getElementById('rbAdhocEditTextarea');
    const adhocRegenerateBtn = document.getElementById('rbAdhocRegenerateBtn');
    const adhocResultEl = document.getElementById('rbAdhocResult');

    let selectedTopics = []; // [{topic_id, topic_title}]
    let checkboxRefs = [];   // non-disabled checkboxes in the current checklist
    let adhocSelectedTopic = null; // {topic_id, topic_title} | null
    let currentAdhocTemplateId = null;
    // Full generated HTML for the current preview — kept around so the
    // "Open Full Preview" button can render it in a real browser tab
    // (a Blob URL) instead of the height-constrained iframe below.
    let currentAdhocPreviewHtml = "";

    function currentReportType() {
        if (typeAdhocRadio && typeAdhocRadio.checked) return 'adhoc';
        if (typeTemplateRadio && typeTemplateRadio.checked) return 'template';
        return typeTrendingRadio && typeTrendingRadio.checked ? 'trending' : 'topic';
    }

    function escapeHtml(s) {
        return String(s || '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    // ── Component checklist ────────────────────────────────────────────
    function renderComponentChecklist(catalog) {
        checklistContainer.innerHTML = '';
        checkboxRefs = [];
        const container = document.createElement('div');
        container.className = 'report-picker-checklist';

        (catalog || []).forEach(comp => {
            const isComingSoon = comp.v1 === false;
            const row = document.createElement('label');
            row.className = 'report-picker-option' + (isComingSoon ? ' disabled' : '');

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = comp.id;
            cb.checked = !isComingSoon;
            cb.disabled = isComingSoon;
            row.appendChild(cb);

            const txt = document.createElement('span');
            txt.className = 'report-picker-option-text';
            const label = document.createElement('strong');
            label.textContent = comp.title || comp.id;
            const desc = document.createElement('span');
            desc.textContent = (comp.description || '') + (isComingSoon ? ' (coming soon)' : '');
            txt.appendChild(label);
            txt.appendChild(desc);
            row.appendChild(txt);

            container.appendChild(row);
            if (!isComingSoon) checkboxRefs.push(cb);
        });

        checklistContainer.appendChild(container);
    }

    async function loadCatalog(type) {
        checklistContainer.innerHTML = '<div class="rb-topic-empty">Loading components…</div>';
        try {
            const res = await fetch(`/api/components?type=${encodeURIComponent(type)}`);
            const catalog = await res.json();
            renderComponentChecklist(catalog);
        } catch (e) {
            checklistContainer.innerHTML = '<div class="rb-topic-empty">Failed to load components.</div>';
        }
    }

    // ── Report type toggle ─────────────────────────────────────────────
    function switchReportType(type) {
        const isTemplate = type === 'template';
        const isAdhoc = type === 'adhoc';
        builtInSection.style.display = (isTemplate || isAdhoc) ? 'none' : '';
        templateSection.style.display = isTemplate ? '' : 'none';
        if (adhocSection) adhocSection.style.display = isAdhoc ? '' : 'none';
        if (isTemplate || isAdhoc) return;
        topicSection.style.display = type === 'topic' ? '' : 'none';
        trendingSection.style.display = type === 'trending' ? '' : 'none';
        loadCatalog(type);
    }
    typeTopicRadio.addEventListener('change', () => switchReportType('topic'));
    typeTrendingRadio.addEventListener('change', () => switchReportType('trending'));
    typeTemplateRadio.addEventListener('change', () => switchReportType('template'));
    if (typeAdhocRadio) typeAdhocRadio.addEventListener('change', () => switchReportType('adhoc'));

    // ── Districts ───────────────────────────────────────────────────────
    async function loadDistricts() {
        try {
            const res = await fetch('/api/districts');
            const data = await res.json();
            (data.districts || []).forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.name;
                opt.textContent = d.name;
                districtFilter.appendChild(opt);
            });
        } catch (e) {
            console.error('Failed to load districts:', e);
        }
    }

    // ── Topic search ────────────────────────────────────────────────────
    function renderTopicResults(topics) {
        if (!topics || topics.length === 0) {
            topicResultsEl.innerHTML = '<div class="rb-topic-empty">No matching topics.</div>';
            return;
        }
        topicResultsEl.innerHTML = '';
        topics.forEach(t => {
            const row = document.createElement('div');
            row.className = 'rb-topic-row';
            row.innerHTML = `
                <span>${escapeHtml(t.topic_title)}</span>
                <span class="rb-topic-meta">${(t.total_no_of_post || 0).toLocaleString()} posts</span>
            `;
            row.addEventListener('click', () => addTopic(t));
            topicResultsEl.appendChild(row);
        });
    }

    let searchDebounce = null;
    async function searchTopics() {
        clearTimeout(searchDebounce);
        searchDebounce = setTimeout(async () => {
            const q = topicSearchInput.value.trim();
            const district = districtFilter.value;
            if (!q) {
                topicResultsEl.innerHTML = '<div class="rb-topic-empty">Start typing to search topics.</div>';
                return;
            }
            topicResultsEl.innerHTML = '<div class="rb-topic-empty">Searching…</div>';
            try {
                const params = new URLSearchParams({ q, district });
                const res = await fetch(`/api/topics/search?${params}`);
                const data = await res.json();
                renderTopicResults(data.topics);
            } catch (e) {
                topicResultsEl.innerHTML = '<div class="rb-topic-empty">Search failed.</div>';
            }
        }, 300);
    }
    topicSearchInput.addEventListener('input', searchTopics);
    districtFilter.addEventListener('change', searchTopics);

    // ── Selected topics (chips, capped at MAX_TOPICS) ──────────────────
    function renderSelectedTopics() {
        selectedTopicsEl.innerHTML = '';
        selectedTopics.forEach(t => {
            const chip = document.createElement('span');
            chip.className = 'rb-chip';
            const label = document.createElement('span');
            label.textContent = t.topic_title;
            chip.appendChild(label);
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.textContent = '×';
            removeBtn.addEventListener('click', () => removeTopic(t.topic_id));
            chip.appendChild(removeBtn);
            selectedTopicsEl.appendChild(chip);
        });
        topicCountEl.textContent = `${selectedTopics.length} / ${MAX_TOPICS} topics selected`;
    }

    function addTopic(t) {
        if (selectedTopics.some(s => s.topic_id === t.unique_topic_id)) return;
        if (selectedTopics.length >= MAX_TOPICS) {
            alert(`You can select up to ${MAX_TOPICS} topics per report.`);
            return;
        }
        selectedTopics.push({ topic_id: t.unique_topic_id, topic_title: t.topic_title });
        renderSelectedTopics();
    }

    function removeTopic(topicId) {
        selectedTopics = selectedTopics.filter(t => t.topic_id !== topicId);
        renderSelectedTopics();
    }

    // ── Generate ────────────────────────────────────────────────────────
    async function generateReport() {
        const reportType = currentReportType();
        const components = checkboxRefs.filter(cb => cb.checked).map(cb => cb.value);
        resultEl.innerHTML = '';

        if (components.length === 0) {
            resultEl.innerHTML = '<div class="rb-result err">Pick at least one component.</div>';
            return;
        }

        const payload = {
            report_type: reportType,
            components,
            custom_instructions: customInstructionsInput.value.trim(),
        };

        if (reportType === 'topic') {
            if (selectedTopics.length === 0) {
                resultEl.innerHTML = '<div class="rb-result err">Select at least one topic.</div>';
                return;
            }
            payload.topics = selectedTopics;
        } else {
            if (!dateFromInput.value) {
                resultEl.innerHTML = '<div class="rb-result err">Pick a start date.</div>';
                return;
            }
            payload.date_range = { from: dateFromInput.value, to: dateToInput.value || dateFromInput.value };
        }

        generateBtn.disabled = true;
        generateBtn.textContent = 'Building report…';
        try {
            const res = await fetch('/api/reports/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || `Request failed (${res.status})`);
            }
            resultEl.innerHTML = `<div class="rb-result ok">✅ Report ready — <a href="${data.download_url}" target="_blank">Download PDF</a> (Reference ID <code>${data.report_id}</code>)</div>`;
        } catch (e) {
            resultEl.innerHTML = `<div class="rb-result err">❌ ${escapeHtml(e.message)}</div>`;
        } finally {
            generateBtn.disabled = false;
            generateBtn.textContent = 'Generate report ▸';
        }
    }
    generateBtn.addEventListener('click', generateReport);

    // ── Custom Template mode ───────────────────────────────────────────
    const templateFileInput = document.getElementById('rbTemplateFile');
    const templateUploadBtn = document.getElementById('rbTemplateUploadBtn');
    const templateListEl = document.getElementById('rbTemplateList');
    const tplTopicSearchInput = document.getElementById('rbTplTopicSearch');
    const tplTopicResultsEl = document.getElementById('rbTplTopicResults');
    const tplSelectedTopicEl = document.getElementById('rbTplSelectedTopic');
    const tplCustomInstructionsInput = document.getElementById('rbTplCustomInstructions');
    const tplGenerateBtn = document.getElementById('rbTplGenerateBtn');
    const tplResultEl = document.getElementById('rbTplResult');

    let templates = [];         // [{template_id, filename, uploaded_at, uploaded_by}]
    let selectedTemplateId = null;
    let tplSelectedTopic = null; // {topic_id, topic_title} | null

    function renderTemplateList() {
        if (templates.length === 0) {
            templateListEl.innerHTML = '<div class="rb-topic-empty">No templates uploaded yet.</div>';
            return;
        }
        templateListEl.innerHTML = '';
        templates.forEach(t => {
            const row = document.createElement('div');
            row.className = 'rb-tpl-row' + (t.template_id === selectedTemplateId ? ' selected' : '');
            row.innerHTML = `
                <span>${escapeHtml(t.filename)}</span>
                <span class="rb-tpl-meta">${escapeHtml((t.uploaded_at || '').split('T')[0] || '')}</span>
            `;
            row.addEventListener('click', () => {
                selectedTemplateId = t.template_id;
                renderTemplateList();
            });
            templateListEl.appendChild(row);
        });
    }

    async function loadTemplates() {
        try {
            const res = await fetch('/api/report-templates');
            if (!res.ok) return; // likely 403 (non-admin) — leave the "no templates" placeholder
            const data = await res.json();
            templates = data.templates || [];
            renderTemplateList();
        } catch (e) {
            console.error('Failed to load templates:', e);
        }
    }

    async function uploadTemplate() {
        const file = templateFileInput.files[0];
        if (!file) {
            alert('Choose an .html file first.');
            return;
        }
        const formData = new FormData();
        formData.append('file', file);
        templateUploadBtn.disabled = true;
        templateUploadBtn.textContent = 'Uploading…';
        try {
            const res = await fetch('/api/report-templates/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || `Upload failed (${res.status})`);
            templates.unshift({ template_id: data.template_id, filename: data.filename, uploaded_at: new Date().toISOString() });
            selectedTemplateId = data.template_id;
            renderTemplateList();
            templateFileInput.value = '';
        } catch (e) {
            alert(`Upload failed: ${e.message}`);
        } finally {
            templateUploadBtn.disabled = false;
            templateUploadBtn.textContent = 'Upload';
        }
    }
    templateUploadBtn.addEventListener('click', uploadTemplate);

    function renderTplTopicResults(topicsFound) {
        if (!topicsFound || topicsFound.length === 0) {
            tplTopicResultsEl.innerHTML = '<div class="rb-topic-empty">No matching topics.</div>';
            return;
        }
        tplTopicResultsEl.innerHTML = '';
        topicsFound.forEach(t => {
            const row = document.createElement('div');
            row.className = 'rb-topic-row';
            row.innerHTML = `
                <span>${escapeHtml(t.topic_title)}</span>
                <span class="rb-topic-meta">${(t.total_no_of_post || 0).toLocaleString()} posts</span>
            `;
            row.addEventListener('click', () => {
                tplSelectedTopic = { topic_id: t.unique_topic_id, topic_title: t.topic_title };
                renderTplSelectedTopic();
            });
            tplTopicResultsEl.appendChild(row);
        });
    }

    let tplSearchDebounce = null;
    async function searchTplTopics() {
        clearTimeout(tplSearchDebounce);
        tplSearchDebounce = setTimeout(async () => {
            const q = tplTopicSearchInput.value.trim();
            if (!q) {
                tplTopicResultsEl.innerHTML = '<div class="rb-topic-empty">Start typing to search topics.</div>';
                return;
            }
            tplTopicResultsEl.innerHTML = '<div class="rb-topic-empty">Searching…</div>';
            try {
                const params = new URLSearchParams({ q, district: 'All' });
                const res = await fetch(`/api/topics/search?${params}`);
                const data = await res.json();
                renderTplTopicResults(data.topics);
            } catch (e) {
                tplTopicResultsEl.innerHTML = '<div class="rb-topic-empty">Search failed.</div>';
            }
        }, 300);
    }
    tplTopicSearchInput.addEventListener('input', searchTplTopics);

    function renderTplSelectedTopic() {
        tplSelectedTopicEl.innerHTML = '';
        if (!tplSelectedTopic) return;
        const chip = document.createElement('span');
        chip.className = 'rb-chip';
        const label = document.createElement('span');
        label.textContent = tplSelectedTopic.topic_title;
        chip.appendChild(label);
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', () => { tplSelectedTopic = null; renderTplSelectedTopic(); });
        chip.appendChild(removeBtn);
        tplSelectedTopicEl.appendChild(chip);
    }

    async function generateFromTemplate() {
        tplResultEl.innerHTML = '';
        if (!selectedTemplateId) {
            tplResultEl.innerHTML = '<div class="rb-result err">Upload or pick a template first.</div>';
            return;
        }
        if (!tplSelectedTopic) {
            tplResultEl.innerHTML = '<div class="rb-result err">Select a topic.</div>';
            return;
        }
        tplGenerateBtn.disabled = true;
        tplGenerateBtn.textContent = 'Reskinning template (this can take a couple minutes)…';
        try {
            const res = await fetch('/api/reports/generate-from-template', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    template_id: selectedTemplateId,
                    topic_id: tplSelectedTopic.topic_id,
                    custom_instructions: tplCustomInstructionsInput.value.trim(),
                }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
            tplResultEl.innerHTML = `<div class="rb-result ok">✅ Report ready — <a href="${data.download_url}" target="_blank">Download PDF</a> (Reference ID <code>${data.report_id}</code>)</div>`;
        } catch (e) {
            tplResultEl.innerHTML = `<div class="rb-result err">❌ ${escapeHtml(e.message)}</div>`;
        } finally {
            tplGenerateBtn.disabled = false;
            tplGenerateBtn.textContent = 'Generate report ▸';
        }
    }
    tplGenerateBtn.addEventListener('click', generateFromTemplate);

    // ── Ad-hoc AI-Generated Layout Mode ────────────────────────────────
    function renderAdhocTopicResults(topicsFound) {
        if (!topicsFound || topicsFound.length === 0) {
            adhocTopicResultsEl.innerHTML = '<div class="rb-topic-empty">No matching topics.</div>';
            return;
        }
        adhocTopicResultsEl.innerHTML = '';
        topicsFound.forEach(t => {
            const row = document.createElement('div');
            row.className = 'rb-topic-row';
            row.innerHTML = `
                <span>${escapeHtml(t.topic_title)}</span>
                <span class="rb-topic-meta">${(t.total_no_of_post || 0).toLocaleString()} posts</span>
            `;
            row.addEventListener('click', () => {
                adhocSelectedTopic = { topic_id: t.unique_topic_id, topic_title: t.topic_title };
                renderAdhocSelectedTopic();
            });
            adhocTopicResultsEl.appendChild(row);
        });
    }

    let adhocSearchDebounce = null;
    async function searchAdhocTopics() {
        clearTimeout(adhocSearchDebounce);
        adhocSearchDebounce = setTimeout(async () => {
            const q = adhocTopicSearchInput.value.trim();
            if (!q) {
                adhocTopicResultsEl.innerHTML = '<div class="rb-topic-empty">Start typing to search topics.</div>';
                return;
            }
            adhocTopicResultsEl.innerHTML = '<div class="rb-topic-empty">Searching…</div>';
            try {
                const params = new URLSearchParams({ q, district: 'All' });
                const res = await fetch(`/api/topics/search?${params}`);
                const data = await res.json();
                renderAdhocTopicResults(data.topics);
            } catch (e) {
                adhocTopicResultsEl.innerHTML = '<div class="rb-topic-empty">Search failed.</div>';
            }
        }, 300);
    }
    if (adhocTopicSearchInput) adhocTopicSearchInput.addEventListener('input', searchAdhocTopics);

    function renderAdhocSelectedTopic() {
        adhocSelectedTopicEl.innerHTML = '';
        if (!adhocSelectedTopic) return;
        const chip = document.createElement('span');
        chip.className = 'rb-chip';
        const label = document.createElement('span');
        label.textContent = adhocSelectedTopic.topic_title;
        chip.appendChild(label);
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', () => { adhocSelectedTopic = null; renderAdhocSelectedTopic(); });
        chip.appendChild(removeBtn);
        adhocSelectedTopicEl.appendChild(chip);
    }

    let adhocExpanded = false;
    if (adhocExpandBtn) {
        adhocExpandBtn.addEventListener('click', () => {
            adhocExpanded = !adhocExpanded;
            adhocPreviewIframe.classList.toggle('expanded', adhocExpanded);
            adhocExpandBtn.textContent = adhocExpanded ? '⤡ Compact View' : '⤢ Expand View';
        });
    }

    // "Open Full Preview" — renders the generated layout in its own browser
    // tab via a Blob URL, so it's shown at real page width/height instead of
    // the cropped, fixed-height iframe. This is the accurate way to judge
    // whether a layout will actually fit a printed/PDF page.
    let adhocOpenFullBtn = null;
    if (adhocExpandBtn) {
        adhocOpenFullBtn = document.createElement('button');
        adhocOpenFullBtn.type = 'button';
        adhocOpenFullBtn.className = adhocExpandBtn.className;
        adhocOpenFullBtn.textContent = '↗ Open Full Preview (new tab)';
        adhocOpenFullBtn.disabled = true;
        adhocOpenFullBtn.style.marginLeft = '8px';
        adhocOpenFullBtn.addEventListener('click', () => {
            if (!currentAdhocPreviewHtml) return;
            const blob = new Blob([currentAdhocPreviewHtml], { type: 'text/html' });
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank');
            // Give the new tab time to load the blob before revoking it.
            setTimeout(() => URL.revokeObjectURL(url), 60000);
        });
        adhocExpandBtn.insertAdjacentElement('afterend', adhocOpenFullBtn);
    }

    async function generateAdhocPreview(customInstructions = "") {
        const promptText = adhocPromptInput.value.trim();
        adhocResultEl.innerHTML = '';
        if (!promptText) {
            adhocResultEl.innerHTML = '<div class="rb-result err">Please enter a layout & design prompt description.</div>';
            return;
        }

        adhocPreviewBtn.disabled = true;
        adhocPreviewBtn.textContent = 'Generating AI Layout Preview…';
        if (adhocRegenerateBtn) {
            adhocRegenerateBtn.disabled = true;
            adhocRegenerateBtn.textContent = 'Regenerating…';
        }

        try {
            const payload = {
                prompt: promptText,
                topic_id: adhocSelectedTopic ? adhocSelectedTopic.topic_id : null,
                custom_instructions: customInstructions,
            };

            const res = await fetch('/api/reports/preview-freeform-adhoc', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || `Preview generation failed (${res.status})`);

            currentAdhocTemplateId = data.template_id;
            currentAdhocPreviewHtml = data.preview_html || '';
            adhocPreviewIframe.srcdoc = data.preview_html || '<p>No preview generated</p>';
            const isReady = data.layout_status === 'ready';
            adhocPreviewMetaEl.innerHTML = `Template: <code>${data.template_id}</code> &nbsp;•&nbsp; <span style="color:${isReady ? '#15803d' : '#b45309'}"><strong>${isReady ? '✓ Layout Verified' : 'ℹ Fallback Reskin Mode'}</strong></span>`;
            adhocPreviewContainer.style.display = '';
            if (adhocOpenFullBtn) adhocOpenFullBtn.disabled = !currentAdhocPreviewHtml;
            adhocResultEl.innerHTML = `<div class="rb-result ok">Preview ready! Review the layout below, then confirm or add edit requirements.</div>`;
        } catch (e) {
            adhocResultEl.innerHTML = `<div class="rb-result err">❌ ${escapeHtml(e.message)}</div>`;
        } finally {
            adhocPreviewBtn.disabled = false;
            adhocPreviewBtn.textContent = 'Generate Layout Preview ▸';
            if (adhocRegenerateBtn) {
                adhocRegenerateBtn.disabled = false;
                adhocRegenerateBtn.textContent = '🔄 Regenerate Preview with Changes';
            }
        }
    }

    if (adhocPreviewBtn) {
        adhocPreviewBtn.addEventListener('click', () => generateAdhocPreview());
    }

    if (adhocRegenerateBtn) {
        adhocRegenerateBtn.addEventListener('click', () => {
            const edits = adhocEditTextarea ? adhocEditTextarea.value.trim() : '';
            if (!edits) {
                alert('Please enter your modified requirements or changes.');
                return;
            }
            generateAdhocPreview(edits);
        });
    }

    async function confirmAdhocReportBuild() {
        if (!currentAdhocTemplateId) {
            adhocResultEl.innerHTML = '<div class="rb-result err">Generate a preview first before building.</div>';
            return;
        }

        adhocConfirmBtn.disabled = true;
        adhocConfirmBtn.textContent = 'Compiling PDF report with live data…';
        adhocResultEl.innerHTML = '';

        try {
            const res = await fetch('/api/reports/confirm-freeform-adhoc', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    template_id: currentAdhocTemplateId,
                    topic_id: adhocSelectedTopic ? adhocSelectedTopic.topic_id : null,
                    custom_instructions: adhocEditTextarea ? adhocEditTextarea.value.trim() : '',
                }),
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || `Build failed (${res.status})`);

            adhocResultEl.innerHTML = `<div class="rb-result ok">✅ Report ready — <a href="${data.download_url}" target="_blank">Download PDF</a> (Reference ID <code>${data.report_id}</code>)</div>`;
        } catch (e) {
            adhocResultEl.innerHTML = `<div class="rb-result err">❌ ${escapeHtml(e.message)}</div>`;
        } finally {
            adhocConfirmBtn.disabled = false;
            adhocConfirmBtn.textContent = 'Looks good, Build with Real Data ▸';
        }
    }

    if (adhocConfirmBtn) {
        adhocConfirmBtn.addEventListener('click', confirmAdhocReportBuild);
    }

    // ── Init ────────────────────────────────────────────────────────────
    loadDistricts();
    loadTemplates();
    switchReportType('topic');
    renderSelectedTopics();
});