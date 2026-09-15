document.addEventListener('DOMContentLoaded', () => {
    const userInput = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');
    const micBtn = document.getElementById('micBtn');
    const stopBtn = document.getElementById('stopBtn');
    const addBtn = document.getElementById('addBtn');
    const pdfFileInput = document.getElementById('pdfFileInput');
    const contentWrapper = document.getElementById('contentWrapper');
    const chatContainer = document.getElementById('chatContainer');
    const messagesDiv = document.getElementById('messages');
    const REPORT_URL = 'monitor_dashboard.html';
    const relatedPanel = document.getElementById('relatedPanel');
    const relatedList = document.getElementById('relatedList');
    const closeRelatedBtn = document.getElementById('closeRelatedBtn');
    const tracePanel = document.getElementById('tracePanel');
    const traceList = document.getElementById('traceList');
    const traceBtn = document.getElementById('traceBtn');
    const closeTraceBtn = document.getElementById('closeTraceBtn');
    const refreshTraceBtn = document.getElementById('refreshTraceBtn');

    let isGenerating = false;
    let currentController = null;
    // This TAB's conversation id — null means "no chat started yet in this
    // tab, the next message starts a new one". Deliberately NOT read from a
    // cookie: cookies are shared by every tab of the same browser, and
    // scoping conversation identity to the browser (not the tab) used to
    // make simultaneous tabs bleed their messages into each other. Set from
    // the URL on load (loadChatFromUrl), from the server's X-Chat-Id
    // response header (sendMessage), or when restoring a past chat
    // (restoreSession) — and cleared on New Chat.
    let currentChatId = null;

    // Auto-grow the input box as the user types multiple lines
    function autoResizeInput() {
        userInput.style.height = 'auto';
        userInput.style.height = Math.min(userInput.scrollHeight, 200) + 'px';
    }

    // Toggle send/mic button based on input, and auto-resize
    userInput.addEventListener('input', () => {
        if (userInput.value.trim().length > 0) {
            sendBtn.style.display = 'flex';
            micBtn.style.display = 'none';
        } else {
            sendBtn.style.display = 'none';
            micBtn.style.display = 'flex';
        }
        autoResizeInput();
    });

    // Enter sends the message, Shift+Enter inserts a new line
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener('click', sendMessage);

    // Stop button: abort an in-flight generation. Also doubles as a manual
    // barge-in trigger — it's the visible button during the two-way
    // speaking phase (mic/send are hidden then), so clicking it interrupts
    // the reply immediately. This is a guaranteed-to-work fallback for
    // automatic voice barge-in, which depends on the mic's echo
    // cancellation actually suppressing the speaker output — that varies a
    // lot by hardware/OS and can silently fail to detect anything at all.
    stopBtn.addEventListener('click', () => {
        if (currentController) {
            currentController.abort();
        }
        if (activeTurnInterrupt) {
            console.debug('[2-Way] Manual interrupt via Stop button.');
            const doInterrupt = activeTurnInterrupt;
            activeTurnInterrupt = null;
            doInterrupt();
        }
    });

    // Switch the input between "generating" (disabled + stop button) and normal state
    function setGeneratingState(generating) {
        isGenerating = generating;
        if (generating) {
            userInput.disabled = true;
            sendBtn.style.display = 'none';
            micBtn.style.display = 'none';
            stopBtn.style.display = 'flex';
        } else {
            userInput.disabled = false;
            stopBtn.style.display = 'none';
            if (userInput.value.trim().length > 0) {
                sendBtn.style.display = 'flex';
                micBtn.style.display = 'none';
            } else {
                sendBtn.style.display = 'none';
                micBtn.style.display = 'flex';
            }
            userInput.focus();
        }
    }

    // Audio recording variables
    let isRecording = false;
    let recognition = null;
    let silenceTimer = null;
    let speechStartTime = null;
    const SILENCE_TIMEOUT_MS = 2000; // auto-stop-and-send this long after the user stops speaking

    // Setup Web Speech API
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    // recognition.continuous = true keeps the recognizer's session open
    // indefinitely — the browser does NOT auto-stop just because the user
    // paused; it only ends on a manual .stop(), an error, or (only if
    // nothing was EVER said) a "no-speech" timeout. So auto-send-on-pause
    // has to be implemented here: every onresult (interim or final) pushes
    // this deadline out; if no new result arrives within SILENCE_TIMEOUT_MS,
    // stop the recognizer ourselves, which fires onend and triggers the
    // existing auto-submit logic there.
    function resetSilenceTimer() {
        clearTimeout(silenceTimer);
        silenceTimer = setTimeout(() => {
            if (!isRecording) return;
            // The Nemotron/selfhosted engine has no `recognition` object to
            // .stop() — finalize+stop it directly instead. The actual
            // auto-send happens once the server's final transcript reply
            // arrives (see startSelfHostedStreaming's ws.onmessage).
            const voiceEngine = localStorage.getItem('voiceEngine') || 'browser';
            if (voiceEngine === 'selfhosted') {
                stopRecording();
            } else if (recognition) {
                recognition.stop();
            }
        }, SILENCE_TIMEOUT_MS);
    }

    function clearSilenceTimer() {
        clearTimeout(silenceTimer);
        silenceTimer = null;
    }

    // ════════════════════════════════════════════════════════════════
    // 2-WAY (HANDS-FREE) VOICE CHAT
    // ════════════════════════════════════════════════════════════════
    // When enabled from Settings: the mic starts listening the instant a
    // message is sent (see sendMessage) and stays listening through BOTH
    // the processing/generating phase AND the spoken-reply phase — not just
    // after the reply is ready — so the user can interrupt at any point in
    // the turn, not only while the reply is being spoken. The existing
    // recognition.onend below auto-submits once the user stops talking.
    let twoWayChatActive = false;

    // Set to a cancel function whenever there's something in-flight that
    // barge-in should be able to cut short: aborting the request while it's
    // still processing (set in sendMessage), or stopping the spoken reply
    // once it starts (set in speakAnswerForTwoWay). null when neither is
    // happening. recognition.onresult below fires it the moment it sees the
    // user start talking.
    let activeTurnInterrupt = null;
    const BARGE_IN_MIN_CHARS = 3; // light debounce against a single stray sound triggering it

    // Normalized text of whatever is currently being spoken (avatar or
    // browser TTS) in two-way mode, '' when nothing is. Used to tell real
    // barge-in apart from the mic simply picking up the assistant's own
    // voice through the speakers — see looksLikeEcho below. This is
    // necessary because the browser's mic echo cancellation is unreliable
    // (varies a lot by hardware/OS, and worse still for the avatar's video
    // audio, which typically isn't covered by the mic's own AEC reference
    // at all) — without it, the recognizer regularly re-hears the reply
    // it's speaking and misreads that as the user interrupting.
    let currentlySpokenText = '';
    let currentlySpokenTextRomanized = '';

    function romanizeDevanagari(text) {
        if (!text) return '';
        const charMap = {
            'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo', 'ऋ': 'ri', 'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'अं': 'an', 'अः': 'ah',
            'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'n',
            'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'n',
            'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
            'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
            'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm',
            'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v', 'श': 'sh', 'ष': 'sh', 'स': 's', 'ह': 'h',
            'ा': 'aa', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo', 'ृ': 'ri', 'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ं': 'n', 'ः': 'h',
            '्': ''
        };
        
        let result = '';
        const consonants = 'कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसह';
        const vowelSignsAndHalant = 'ािीुूृेैोौंः्';
        
        for (let i = 0; i < text.length; i++) {
            const char = text[i];
            const nextChar = text[i + 1];
            
            if (charMap[char] !== undefined) {
                result += charMap[char];
                const isConsonant = consonants.includes(char);
                const nextIsVowelSignOrHalant = nextChar && vowelSignsAndHalant.includes(nextChar);
                const nextIsSpaceOrNull = !nextChar || nextChar === ' ';
                if (isConsonant && !nextIsVowelSignOrHalant && !nextIsSpaceOrNull) {
                    result += 'a';
                }
            } else {
                result += char;
            }
        }
        return result;
    }

    function roughPhonetic(str) {
        return (str || '')
            .toLowerCase()
            .replace(/aa/g, 'a')
            .replace(/ee/g, 'i')
            .replace(/oo/g, 'u')
            .replace(/y\b/g, 'i')
            .replace(/y/g, 'i')
            .replace(/kh/g, 'k')
            .replace(/gh/g, 'g')
            .replace(/jh/g, 'j')
            .replace(/bh/g, 'b')
            .replace(/dh/g, 'd')
            .replace(/ph/g, 'p')
            .replace(/sh/g, 's')
            .replace(/[^a-z0-9\s]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function normalizeForEchoCheck(str) {
        // Keep Latin + Devanagari letters/digits/spaces only, so Hindi and
        // English replies are both compared fairly.
        return (str || '')
            .toLowerCase()
            .replace(/[^a-z0-9ऀ-ॿ\s]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function looksLikeEcho(transcript) {
        if (!currentlySpokenText) return false;
        const norm = normalizeForEchoCheck(transcript);
        if (!norm) return false;

        const heardWordsNorm = norm.split(' ').filter(Boolean);
        if (heardWordsNorm.length === 0) return false;

        const spokenNorm = normalizeForEchoCheck(currentlySpokenText);
        const spokenPhonetic = currentlySpokenTextRomanized ? roughPhonetic(currentlySpokenTextRomanized) : '';

        // 1. Single word check: if only 1 word was heard
        if (heardWordsNorm.length === 1) {
            const singleWord = heardWordsNorm[0];
            const singlePhonetic = roughPhonetic(singleWord);

            // A single word is almost always what the FIRST chunk of any
            // interruption looks like (interim results arrive word-by-word).
            // Matching it against the entire spoken reply "anywhere at all"
            // is fine for a short reply, but for a normal multi-sentence one
            // the odds of a real interrupting word ("stop", "wait", or just
            // the first word of a follow-up question) coincidentally
            // matching SOME word in that whole paragraph are high — which
            // was making barge-in swallow real short interruptions almost
            // every time instead of stopping the speech. Letting an
            // occasional genuine one-word echo slip through here is a much
            // smaller cost than barge-in silently never firing.
            const spokenWordCount = spokenNorm.split(' ').filter(Boolean).length;
            if (spokenWordCount > 8) {
                console.debug('[2-Way] Echo guard: single word vs long reply, treating as real speech.', { singleWord, spokenWordCount });
                return false;
            }

            const isSingleInNorm = spokenNorm.split(' ').includes(singleWord);
            const isSingleInPhonetic = spokenPhonetic ? spokenPhonetic.split(' ').includes(singlePhonetic) : false;

            const isEcho = isSingleInNorm || isSingleInPhonetic;
            console.debug('[2-Way] Echo guard check (Single word):', { singleWord, isEcho });
            return isEcho;
        }

        // 2. Multi-word phrase check: Consecutive Word Pair (Bigram) Sequence Matching
        // In AI echo, the speaker plays words in the EXACT consecutive order of the AI sentence.
        // In human speech (even when repeating key topic words), the user creates new consecutive word pairs.
        let matchBigrams = 0;
        const totalBigrams = heardWordsNorm.length - 1;

        const heardPhonetic = roughPhonetic(transcript).split(' ').filter(Boolean);
        const aiPhoneticNorm = spokenPhonetic ? roughPhonetic(spokenPhonetic) : '';

        for (let i = 0; i < totalBigrams; i++) {
            const pairNorm = heardWordsNorm[i] + ' ' + heardWordsNorm[i+1];
            const pairPhonetic = (heardPhonetic[i] || '') + ' ' + (heardPhonetic[i+1] || '');

            const inNormAI = spokenNorm.includes(pairNorm);
            const inPhoneticAI = aiPhoneticNorm ? aiPhoneticNorm.includes(pairPhonetic) : false;

            if (inNormAI || inPhoneticAI) {
                matchBigrams++;
            }
        }

        const bigramRatio = matchBigrams / totalBigrams;

        // Audio is an Echo if 50% or more of the consecutive 2-word phrases match the AI's exact spoken sequence.
        const isEcho = bigramRatio >= 0.50;

        console.debug('[2-Way] Echo guard check (Bigram Sequence):', { transcript, matchBigrams, totalBigrams, bigramRatio, isEcho });
        return isEcho;
    }

    function startTwoWayListening() {
        if (!twoWayChatActive || isRecording) return;
        const voiceEngine = localStorage.getItem('voiceEngine') || 'browser';
        if (voiceEngine === 'browser' && !SpeechRecognition) return;
        console.debug('[2-Way] Starting mic with engine:', voiceEngine);
        micBtn.click();
    }

    let currentElevenLabsAudio = null;
    let currentElevenLabsAudioUrl = null;
    function stopElevenLabsAudio() {
        if (currentElevenLabsAudio) {
            currentElevenLabsAudio.onended = null;
            currentElevenLabsAudio.onerror = null;
            currentElevenLabsAudio.pause();
            currentElevenLabsAudio = null;
        }
        if (currentElevenLabsAudioUrl) {
            URL.revokeObjectURL(currentElevenLabsAudioUrl);
            currentElevenLabsAudioUrl = null;
        }
    }

    // Fetches the server's ElevenLabs voice for `text` (rotates through the
    // saved key pool, see /api/tts) and resolves to a ready-to-play but not
    // yet playing <audio>, or null on any failure — no keys saved, every
    // saved key quota-exceeded, or a network error — so callers fall back
    // to the browser's own (much lower quality, quieter) speechSynthesis.
    // Deliberately doesn't play/await here so callers keep control of
    // playback timing and can wire up their own interrupt handling.
    async function fetchElevenLabsAudio(text) {
        if (!text) return null;
        try {
            const res = await fetch('/api/tts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text })
            });
            if (!res.ok) return null;
            const blob = await res.blob();
            const audio = new Audio(URL.createObjectURL(blob));
            audio.volume = 1.0;
            return audio;
        } catch (e) {
            console.warn('ElevenLabs TTS fetch failed, falling back to browser voice:', e);
            return null;
        }
    }

    // Plain browser SpeechSynthesis fallback, used whenever ElevenLabs is
    // unavailable (no keys saved / all keys exhausted / offline).
    function speakWithBrowserTts(text, { onend, onerror } = {}) {
        if (!window.speechSynthesis || !text) { if (onend) onend(); return; }
        const currentLang = window.i18n?.getLanguage() || 'en';
        const langCode = currentLang === 'hi' ? 'hi-IN' : (currentLang === 'hinglish' ? 'hi-IN' : 'en-US');
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = langCode;
        const bestVoice = getBestVoice ? getBestVoice(langCode) : null;
        if (bestVoice) utterance.voice = bestVoice;
        utterance.rate = 0.92;
        utterance.pitch = 1.0;
        utterance.volume = 1.0;
        if (onend) utterance.onend = onend;
        if (onerror) utterance.onerror = onerror;
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(utterance);
    }

    // Picks the most human-sounding available voice for the given lang code.
    // Prefers exact locale matches first, then a strong English voice, then
    // neural/natural/premium/enhanced voices, finally any voice for that lang.
    function getBestVoice(langCode) {
        const voices = window.speechSynthesis.getVoices();
        if (!voices.length) return null;

        const lang = String(langCode || 'en-US').toLowerCase();
        const prefix = lang.split('-')[0];
        const exactLocale = voices.filter(v => v.lang.toLowerCase() === lang);
        const sameLangFamily = voices.filter(v => v.lang.toLowerCase().startsWith(prefix));
        const pool = exactLocale.length ? exactLocale : (sameLangFamily.length ? sameLangFamily : voices);

        const scoreVoice = (voice) => {
            const name = (voice.name || '').toLowerCase();
            const langName = (voice.lang || '').toLowerCase();
            let score = 0;

            // Prefer exact locale token, especially en-US. This keeps the
            // listen-btn aligned with English instead of an accidental regional/hindi
            // voice that still matches the broader "en" family.
            if (langName === 'en-us') score += 200;
            if (langName === 'en-gb') score += 190;
            if (langName.startsWith('en-')) score += 150;
            if (langName.startsWith('hi-')) score += 30;

            if (/neural/.test(name)) score += 60;
            if (/natural/.test(name)) score += 55;
            if (/premium/.test(name)) score += 50;
            if (/enhanced/.test(name)) score += 45;
            if (/google/.test(name)) score += 40;
            if (/wave/.test(name)) score += 35;
            if (/samantha|zira|aria|daisy|jenny|olivia|fiona/.test(name)) score += 25;
            if (/(female|woman)/.test(name)) score += 5;
            return score;
        };

        return [...pool].sort((a, b) => scoreVoice(b) - scoreVoice(a))[0] || null;
    }

    // Speaks `text` and resolves once it's done (naturally, or because it
    // was interrupted) — via the avatar if its widget is open, else
    // ElevenLabs (falling back to the browser's own speech synthesis when no
    // key is configured/all keys are exhausted), so the loop still works
    // without an avatar. Only used in two-way mode; normal single-turn use
    // keeps the old fire-and-forget avatar call untouched.
    // Settings > 2-Way Chat > "Speak replies out loud" is a mute switch on
    // THIS function only — when off, the listen/auto-send/re-listen loop
    // and the avatar's normal speaking outside 2-Way Chat both keep working
    // exactly as before, this just skips producing any audio here.
    // Plain-chat TTS (no avatar widget open) speaks "output is <answer>",
    // with punctuation stripped to plain spaces first — some speech engines
    // read "." as "dot" or "!" as "exclamation mark" instead of just pausing,
    // so e.g. "hello himanshu!" is spoken as the words "output is hello
    // himanshu", never the literal "!" character. The avatar widget path is
    // untouched — it still speaks the real, unmodified `text`.
    function buildChatSpokenText(rawText) {
        const cleaned = (rawText || '')
            .replace(/[.,!?;:*_`#>|~^"'()\[\]{}]/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
        return cleaned ? `output is ${cleaned}` : '';
    }

    function speakAnswerForTwoWay(text) {
        const avatarOpen = window.isAvatarWidgetOpen ? window.isAvatarWidgetOpen() : false;
        const spokenText = avatarOpen ? text : buildChatSpokenText(text);

        currentlySpokenText = normalizeForEchoCheck(spokenText);
        currentlySpokenTextRomanized = normalizeForEchoCheck(romanizeDevanagari(spokenText));

        return new Promise((resolve) => {
            let settled = false;
            const finish = () => {
                if (settled) return;
                settled = true;
                activeTurnInterrupt = null;
                currentlySpokenText = '';
                currentlySpokenTextRomanized = '';
                resolve();
            };

            // recognition.onresult calls this the moment it sees the user
            // start talking. Best-effort cancel on whichever channel is
            // actually speaking; finish() resolves immediately rather than
            // waiting on the cancel to also fire its own end/error callback,
            // since some SDKs don't guarantee that callback fires at all
            // once interrupted.
            activeTurnInterrupt = () => {
                console.debug('[2-Way] Interrupting speech.');
                if (avatarOpen && window.avatarInterruptIfActive) window.avatarInterruptIfActive();
                if (!avatarOpen) {
                    stopElevenLabsAudio();
                    if (window.speechSynthesis) window.speechSynthesis.cancel();
                }
                finish();
            };

            console.debug('[2-Way] Speaking started, barge-in armed.', { avatarOpen, chars: spokenText.length });

            if (avatarOpen) {
                if (window.avatarSpeakIfActive) {
                    window.avatarSpeakIfActive(text).finally(finish);
                } else {
                    finish();
                }
            } else {
                if (!spokenText) { finish(); return; }
                fetchElevenLabsAudio(spokenText).then((audio) => {
                    if (settled) { stopElevenLabsAudio(); return; } // interrupted while the fetch was in flight
                    if (audio) {
                        currentElevenLabsAudio = audio;
                        currentElevenLabsAudioUrl = audio.src;
                        audio.onended = finish;
                        audio.onerror = () => { stopElevenLabsAudio(); speakWithBrowserTts(spokenText, { onend: finish, onerror: finish }); };
                        audio.play().catch(() => { stopElevenLabsAudio(); speakWithBrowserTts(spokenText, { onend: finish, onerror: finish }); });
                    } else {
                        speakWithBrowserTts(spokenText, { onend: finish, onerror: finish });
                    }
                });
            }
        });
    }

    // Exposed to settings.js so the Settings toggle can start/stop the loop
    // immediately, the same way avatarSpeakIfActive is exposed the other way.
    window.setTwoWayChatEnabled = function (enabled) {
        twoWayChatActive = !!enabled;
        if (twoWayChatActive) {
            startTwoWayListening();
        } else if (isRecording) {
            if (recognition) recognition.stop();
            stopRecording();
        }
    };

    // ════════════════════════════════════════════════════════════════
    // SELF-HOSTED STREAMING ASR (NEMOTRON 3.5 ASR WEBSOCKET)
    // ════════════════════════════════════════════════════════════════
    let activeWebSocketSession = null;
    let audioContext = null;
    let mediaStream = null;

    // The server re-transcribes its ENTIRE accumulated audio buffer on
    // every chunk it receives (see NemotronAudioStreamSession.process_buffer
    // in server.py — it's never cleared until finalize/reset), not just
    // newly-arrived audio. So during silence it keeps re-sending the exact
    // same transcript text every ~250ms for as long as the mic stays open.
    // Track the last text seen so resetSilenceTimer only fires on genuinely
    // NEW speech — otherwise these repeated identical messages kept
    // re-arming the silence timer forever and auto-send never triggered,
    // no matter how long the user actually stayed silent.
    let lastNemotronTranscript = '';

    // Guards startSelfHostedStreaming against the overlapping-session race
    // below — bumped on every call, and every async callback checks it's
    // still the current session before touching shared state (mirrors the
    // `thisRecognition !== recognition` guard the browser engine already
    // uses for the same reason).
    let selfHostedSessionId = 0;

    function startSelfHostedStreaming() {
        if (isRecording) return;
        // Set synchronously, BEFORE any await — this used to only get set
        // inside ws.onopen, AFTER both the WebSocket handshake and the
        // mic-permission prompt resolved. Two-Way Chat calls
        // startTwoWayListening() from two places per turn (request start,
        // and again once the reply is ready to speak) as a "just in case
        // it isn't already running" safety net; with isRecording still
        // false during that whole async window, the second call sailed
        // past its `if (isRecording) return` guard and opened a SECOND,
        // overlapping WebSocket + mic session on top of the first — both
        // sharing the same activeWebSocketSession/audioContext/mediaStream
        // variables, corrupting each other's state (this is what the
        // repeated "Starting mic"/barge-in-loop pattern in the console was).
        isRecording = true;
        lastNemotronTranscript = '';
        const thisSessionId = ++selfHostedSessionId;
        const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${location.host}/api/ws/transcribe`;

        console.debug('[Nemotron ASR] Connecting WebSocket:', wsUrl);
        const ws = new WebSocket(wsUrl);
        activeWebSocketSession = ws;

        ws.onopen = async () => {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: { sampleRate: 16000, channelCount: 1 } });
                // A newer session started (or this one was stopped) while
                // getUserMedia was pending — abandon this one instead of
                // clobbering the newer session's mediaStream/audioContext.
                if (thisSessionId !== selfHostedSessionId) {
                    stream.getTracks().forEach(track => track.stop());
                    return;
                }
                mediaStream = stream;
                audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
                const source = audioContext.createMediaStreamSource(mediaStream);
                const processor = audioContext.createScriptProcessor(4096, 1, 1);

                source.connect(processor);
                processor.connect(audioContext.destination);

                processor.onaudioprocess = (e) => {
                    if (thisSessionId !== selfHostedSessionId || ws.readyState !== WebSocket.OPEN) return;
                    const inputData = e.inputBuffer.getChannelData(0);
                    // Convert float32 [-1, 1] to 16-bit PCM Int16
                    const int16Buffer = new Int16Array(inputData.length);
                    for (let i = 0; i < inputData.length; i++) {
                        const s = Math.max(-1, Math.min(1, inputData[i]));
                        int16Buffer[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                    }
                    ws.send(int16Buffer.buffer);
                };

                micBtn.innerHTML = '<i data-lucide="square" style="color: #ef4444;"></i>';
                if (window.lucide) lucide.createIcons();
                micBtn.classList.add("recording-active");
                userInput.placeholder = "Listening (Nemotron ASR)... Speak now";

            } catch (err) {
                console.error("[Nemotron ASR] Mic stream failed:", err);
                alert("Microphone access failed: " + err.message);
                stopRecording();
            }
        };

        ws.onmessage = (event) => {
            // A stale/superseded session's late reply (see thisSessionId
            // above) — ignore it instead of acting on shared state
            // (userInput, activeTurnInterrupt, sendMessage) on behalf of a
            // session that's no longer the active one.
            if (thisSessionId !== selfHostedSessionId) return;
            try {
                const data = JSON.parse(event.data);
                // Server sends this when the Nemotron model never loaded (missing
                // NeMo/transformers dependency, or an incompatible torch version)
                // — previously it just sent nothing at all, so the mic sat there
                // "listening" forever with no transcript and no indication why.
                if (data.type === 'error') {
                    console.error('[Nemotron ASR]', data.message);
                    alert(`Self-hosted (Nemotron ASR) unavailable: ${data.message}`);
                    localStorage.setItem('voiceEngine', 'browser');
                    const engineSelect = document.getElementById('voiceEngineSelect');
                    if (engineSelect) engineSelect.value = 'browser';
                    stopRecording();
                    return;
                }
                if (data.type === 'transcript' && data.text && !data.is_final) {
                    const transcript = data.text;
                    // Same text as last message — the server re-transcribed its
                    // whole buffer again (see lastNemotronTranscript's comment
                    // above) but found nothing new. Not fresh speech, so don't
                    // touch the silence timer — otherwise it never expires no
                    // matter how long the user actually stays silent, since the
                    // server keeps re-sending this as long as the mic is open.
                    if (transcript === lastNemotronTranscript) return;
                    lastNemotronTranscript = transcript;

                    if (looksLikeEcho(transcript)) return;

                    userInput.value = transcript;
                    if (transcript.length > 0 && !speechStartTime) {
                        speechStartTime = Date.now();
                    }
                    resetSilenceTimer();

                    if (activeTurnInterrupt && transcript.length >= BARGE_IN_MIN_CHARS) {
                        const doInterrupt = activeTurnInterrupt;
                        activeTurnInterrupt = null;
                        doInterrupt();
                    }
                }

                // Sent once, in reply to the 'finalize' message stopSelfHostedStreaming
                // sends when recording stops (silence timeout or a manual mic click) —
                // this is the Nemotron-engine equivalent of the browser engine's
                // recognition.onend, which is where ITS auto-submit happens. Without
                // this, nothing ever actually called sendMessage() for this engine —
                // the transcript would just sit in the input box forever.
                if (data.type === 'transcript' && data.is_final) {
                    if (ws.readyState === WebSocket.OPEN) ws.close();
                    const text = (data.text || userInput.value || '').trim();
                    if (text) {
                        userInput.value = text;
                        userInput.dispatchEvent(new Event('input'));
                        // Tag this turn as voice-originated (self-hosted Nemotron ASR)
                        // so the backend can apply extra entity-grounding scrutiny to
                        // it instead of trusting the transcript as-is — see
                        // sendMessage()'s inputSource handling below.
                        sendMessage({ inputSource: 'voice' });
                    } else if (twoWayChatActive) {
                        // Nothing said — same as the browser engine's silent-restart
                        // case, keep the 2-Way Chat loop alive instead of going idle.
                        startTwoWayListening();
                    }
                }
            } catch (e) {
                console.error("[Nemotron ASR] WebSocket message error:", e);
            }
        };

        // Previously missing entirely — if the WebSocket itself couldn't
        // connect (server down, endpoint unreachable), the mic click just did
        // nothing with zero feedback since onopen (where the "recording" UI
        // state gets set) never fires either.
        ws.onerror = (event) => {
            console.error("[Nemotron ASR] WebSocket error:", event);
            if (!isRecording) {
                alert("Self-hosted (Nemotron ASR) connection failed — switch to Browser Native in Settings.");
            }
        };

        ws.onclose = () => {
            console.debug("[Nemotron ASR] WebSocket closed.");
        };
    }

    function stopSelfHostedStreaming() {
        if (activeWebSocketSession) {
            if (activeWebSocketSession.readyState === WebSocket.OPEN) {
                const ws = activeWebSocketSession;
                ws.send(JSON.stringify({ action: "finalize" }));
                // Don't close() here — closing in the same tick as the
                // finalize send raced the server's is_final reply (which is
                // what actually triggers auto-send, see ws.onmessage above)
                // and could cut it off before it arrived. ws.onmessage closes
                // it once that reply lands; this is just a safety net in case
                // it never does (e.g. the server errored mid-finalize).
                setTimeout(() => {
                    if (ws.readyState === WebSocket.OPEN) ws.close();
                }, 5000);
            }
            activeWebSocketSession = null;
        }
        if (mediaStream) {
            mediaStream.getTracks().forEach(track => track.stop());
            mediaStream = null;
        }
        if (audioContext) {
            try { audioContext.close(); } catch (e) {}
            audioContext = null;
        }
    }

    // Mic click handler
    micBtn.addEventListener('click', () => {
        const voiceEngine = localStorage.getItem('voiceEngine') || 'browser';
        
        if (voiceEngine === 'selfhosted') {
            if (!isRecording) {
                startSelfHostedStreaming();
            } else {
                stopRecording();
            }
            return;
        }

        if (!SpeechRecognition) {
            alert("Speech recognition is not supported in this browser. Use Chrome or Edge, or switch to Self-Hosted Nemotron ASR in Settings.");
            return;
        }

        if (!isRecording) {
            recognition = new SpeechRecognition();
            const thisRecognition = recognition;
            const currentLang = window.i18n?.getLanguage() || 'en';
            recognition.lang = currentLang === 'hi' ? 'hi-IN' : 'en-IN';
            recognition.interimResults = true;
            const isMobileDevice = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
            recognition.continuous = !isMobileDevice;

            recognition.onstart = () => {
                if (recognition !== thisRecognition) return;
                console.debug('[2-Way] Mic actually started (onstart fired).', { armedForBargeIn: !!activeTurnInterrupt });
            };

            recognition.onresult = (event) => {
                if (recognition !== thisRecognition) return;
                let transcript = '';
                for (let i = 0; i < event.results.length; i++) {
                    transcript += event.results[i][0].transcript;
                }
                
                if (looksLikeEcho(transcript)) {
                    console.debug('[2-Way] Ignoring likely echo of the assistant\'s own voice:', transcript);
                    return;
                }

                let cleanTranscript = transcript;
                if (currentlySpokenText) {
                    const spokenWords = currentlySpokenText.split(' ').filter(Boolean);
                    const spokenWordsPhonetic = currentlySpokenTextRomanized ? roughPhonetic(currentlySpokenTextRomanized).split(' ').filter(Boolean) : [];
                    const heardWords = transcript.split(' ');
                    const filtered = heardWords.filter(w => {
                        const normW = normalizeForEchoCheck(w);
                        const phoneticW = roughPhonetic(w);
                        return !spokenWords.includes(normW) && !spokenWordsPhonetic.includes(phoneticW);
                    });
                    cleanTranscript = filtered.join(' ').trim();
                }

                userInput.value = cleanTranscript;
                console.debug('[2-Way] onresult (clean):', cleanTranscript, { raw: transcript, armedForBargeIn: !!activeTurnInterrupt });
                
                if (cleanTranscript.length > 0) {
                    if (!speechStartTime) {
                        speechStartTime = Date.now();
                    }
                    resetSilenceTimer();
                }

                if (activeTurnInterrupt && cleanTranscript.length >= BARGE_IN_MIN_CHARS) {
                    const doInterrupt = activeTurnInterrupt;
                    activeTurnInterrupt = null;
                    doInterrupt();
                }
            };

            recognition.onerror = (event) => {
                if (recognition !== thisRecognition) return;
                console.error('Speech error:', event.error);
                const wasTwoWay = twoWayChatActive;
                const isTransientRestart = wasTwoWay && event.error !== 'not-allowed';
                stopRecording(isTransientRestart);
                if (event.error === 'not-allowed') {
                    alert('Microphone access denied. Please allow microphone permission.');
                    twoWayChatActive = false;
                    window.settingsManager?.disableTwoWayChat();
                } else if (isTransientRestart) {
                    startTwoWayListening();
                }
            };

            recognition.onend = () => {
                if (recognition !== thisRecognition) return;
                if (isRecording) {
                    const text = userInput.value.trim();
                    const wasTwoWay = twoWayChatActive;
                    
                    let isShortSpeech = false;
                    if (text && speechStartTime) {
                        const speechDurationSec = (Date.now() - speechStartTime) / 1000;
                        const wordCount = text.split(/\s+/).filter(Boolean).length;
                        console.debug('[2-Way] Speech duration check:', { speechDurationSec, wordCount });
                        if (speechDurationSec < 2.0 && wordCount < 3) {
                            isShortSpeech = true;
                            console.warn('[2-Way] Speech discarded as disturbance/noise:', { text, speechDurationSec, wordCount });
                        }
                    }

                    const isSilentRestart = (!text || isShortSpeech) && wasTwoWay;
                    stopRecording(isSilentRestart);
                    
                    if (text && !isShortSpeech) {
                        userInput.dispatchEvent(new Event('input'));
                        // Tag this turn as voice-originated (browser SpeechRecognition)
                        // so the backend can apply extra entity-grounding scrutiny to
                        // it instead of trusting the transcript as-is — see
                        // sendMessage()'s inputSource handling below.
                        sendMessage({ inputSource: 'voice' });
                    } else if (isSilentRestart) {
                        userInput.value = '';
                        userInput.dispatchEvent(new Event('input'));
                        startTwoWayListening();
                    }
                }
            };

            recognition.start();
            isRecording = true;

            micBtn.innerHTML = '<i data-lucide="square" style="color: #ef4444;"></i>';
            if (window.lucide) lucide.createIcons();
            micBtn.classList.add("recording-active");
            userInput.placeholder = "Listening... Speak now";

        } else {
            if (recognition) recognition.stop();
            stopRecording();
        }
    });

    function stopRecording(keepListeningUI = false) {
        isRecording = false;
        clearSilenceTimer();
        speechStartTime = null;
        stopSelfHostedStreaming();
        if (keepListeningUI) return;
        micBtn.innerHTML = '<i data-lucide="mic"></i>';
        if (window.lucide) lucide.createIcons();
        micBtn.classList.remove("recording-active");
        userInput.placeholder = "Ask smart SMI...";
    }

    // PDF upload: "+" button opens the hidden file input, selecting a file uploads it
    addBtn.addEventListener('click', () => {
        pdfFileInput.click();
    });

    pdfFileInput.addEventListener('change', async () => {
        const files = Array.from(pdfFileInput.files);
        pdfFileInput.value = '';
        if (!files.length) return;

        if (!contentWrapper.classList.contains('chat-active')) {
            contentWrapper.classList.add('chat-active');
        }

        addBtn.disabled = true;
        addBtn.innerHTML = '<i data-lucide="loader-2" class="spin"></i>';
        if (window.lucide) lucide.createIcons();

        for (const file of files) {
            const formData = new FormData();
            formData.append('file', file, file.name);

            try {
                const response = await fetch('/api/upload-pdf', { method: 'POST', body: formData });
                const data = await response.json();

                if (!response.ok || data.error) {
                    throw new Error(data.error || 'Upload failed');
                }

                const confirmationHtml = marked.parse(
                    `📄 Uploaded **${data.filename}** — ${data.pages} pages, ${data.chunks} chunks indexed. Ask me anything about it.`
                );
                addMessage(confirmationHtml, 'ai', null, true);
            } catch (error) {
                console.error('PDF upload error:', error);
                addMessage(`Sorry, I couldn't process **${file.name}**: ${error.message}`, 'ai');
            }
        }

        addBtn.disabled = false;
        addBtn.innerHTML = '<i data-lucide="plus"></i>';
        if (window.lucide) lucide.createIcons();
        chatContainer.scrollTop = chatContainer.scrollHeight;

        // Re-cluster this session's PDFs into subject "experts" now that a new
        // batch has finished uploading (see the avatar widget module, which
        // reads /api/pdf-experts to offer per-subject avatar faces).
        if (window.rebuildPdfExperts) window.rebuildPdfExperts();
    });

    // Model Selector Logic
    const modelSelectBtn = document.getElementById('modelSelectBtn');
    const modelDropdown = document.getElementById('modelDropdown');
    const modelLabel = document.getElementById('modelLabel');
    const modelOptions = document.querySelectorAll('.model-option');
    let currentLimit = '50';

    if (modelSelectBtn && modelDropdown) {
        modelSelectBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            modelDropdown.classList.toggle('show');
        });

        modelOptions.forEach(option => {
            option.addEventListener('click', () => {
                modelOptions.forEach(opt => opt.classList.remove('active'));
                option.classList.add('active');
                currentLimit = option.dataset.model;
                modelLabel.textContent = option.textContent;
                modelDropdown.classList.remove('show');
            });
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!modelSelectBtn.contains(e.target) && !modelDropdown.contains(e.target)) {
                modelDropdown.classList.remove('show');
            }
        });
    }

    // Handle New Chat
    const newChatBtns = document.querySelectorAll('.new-chat-btn');
    newChatBtns.forEach(btn => {
        btn.addEventListener('click', async () => {
            // Abort any in-flight generation before resetting
            if (currentController) currentController.abort();

            // Reset UI
            messagesDiv.innerHTML = '';
            contentWrapper.classList.remove('chat-active');
            userInput.value = '';
            autoResizeInput();
            setGeneratingState(false);

            // Forget this tab's chat_id — the next message starts a new one
            // server-side and reports its id back via X-Chat-Id.
            currentChatId = null;

            // Back to the bare URL — the next message will push a fresh /c/<chatId>
            if (window.location.pathname !== '/') {
                history.pushState({}, '', '/');
            }

            // Tell backend to clear session history and save to past
            try {
                await fetch('/api/clear', { method: 'POST' });
                // Refresh whichever history list(s) are currently visible
                refreshAllHistoryLists();
            } catch (e) {
                console.error('Error clearing chat history:', e);
            }
        });
    });

    // Handle History Panel
    const historyBtn = document.getElementById('historyBtn');
    const closeHistoryBtn = document.getElementById('closeHistoryBtn');
    const historyPanel = document.getElementById('historyPanel');
    const historyList = document.getElementById('historyList');
    // Mobile hamburger drawer's inline "Recent Chats" list (index.html) —
    // #historyBtn (and the rest of .sidebar) is hidden on mobile, so this is
    // the only way to reach chat history there. Same markup/classes as
    // historyList above, just a second render target.
    const hamburgerHistoryList = document.getElementById('hamburgerHistoryList');

    historyBtn?.addEventListener('click', () => {
        historyPanel.classList.add('open');
        loadHistory(historyList);
    });

    closeHistoryBtn.addEventListener('click', () => {
        historyPanel.classList.remove('open');
    });

    // Renders the chat history list into `container` — either the desktop
    // history panel's list or the mobile hamburger drawer's inline copy.
    async function loadHistory(container) {
        if (!container) return;
        try {
            const response = await fetch('/api/history');
            const data = await response.json();
            container.innerHTML = '';

            if (data.history.length === 0) {
                container.innerHTML = '<div style="color: var(--text-secondary); text-align: center; margin-top: 20px;">No recent chats</div>';
                return;
            }

            data.history.forEach(session => {
                const itemContainer = document.createElement('div');
                itemContainer.className = 'history-item-container';

                const item = document.createElement('button');
                item.className = 'history-item';
                item.innerHTML = `
                    <div class="history-item-title">${session.title}</div>
                    <div class="history-item-date">${session.date}</div>
                    <div class="history-item-id">Chat ID: ${session.id}</div>
                `;
                item.addEventListener('click', () => restoreSession(session.id));

                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'delete-history-btn icon-btn';
                deleteBtn.innerHTML = '<i data-lucide="trash-2"></i>';
                deleteBtn.title = 'Delete Chat';
                deleteBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    try {
                        const res = await fetch(`/api/history/${session.id}`, { method: 'DELETE' });
                        if (res.ok) {
                            refreshAllHistoryLists();
                        }
                    } catch (err) {
                        console.error('Error deleting session:', err);
                    }
                });

                itemContainer.appendChild(item);
                itemContainer.appendChild(deleteBtn);
                container.appendChild(itemContainer);
            });

            // Re-render lucide icons for newly added elements
            if (window.lucide) {
                lucide.createIcons();
            }
        } catch (e) {
            console.error('Error loading history:', e);
        }
    }

    // Keeps both copies of the history list (desktop panel + mobile drawer)
    // in sync instead of only refreshing whichever one is currently open.
    function refreshAllHistoryLists() {
        if (historyPanel.classList.contains('open')) loadHistory(historyList);
        if (hamburgerHistoryList) loadHistory(hamburgerHistoryList);
    }

    // Called from index.html's hamburger-drawer script (separate scope —
    // this closure isn't global) each time the drawer opens.
    window.refreshMobileHistoryDrawer = () => loadHistory(hamburgerHistoryList);

    // Records `chatId` as this tab's conversation and pushes /c/<chatId>
    // into the address bar (ChatGPT-style) without a page reload, unless
    // we're already there. Shared by sendMessage (via the X-Chat-Id
    // response header) and restoreSession below.
    function updateUrlForChatId(chatId) {
        if (!chatId) return;
        currentChatId = chatId;
        const targetPath = `/c/${chatId}`;
        if (window.location.pathname !== targetPath) {
            history.pushState({ chatId }, '', targetPath);
        }
    }

    async function restoreSession(sessionId) {
        try {
            const response = await fetch(`/api/restore/${sessionId}`, { method: 'POST' });
            const data = await response.json();

            if (data.status === 'restored') {
                // Clear UI
                messagesDiv.innerHTML = '';
                if (!contentWrapper.classList.contains('chat-active')) {
                    contentWrapper.classList.add('chat-active');
                }

                // Re-render all messages
                data.messages.forEach(msg => {
                    const isAi = msg.role === 'assistant';
                    const content = isAi ? marked.parse(msg.content) : msg.content;
                    addMessage(content, isAi ? 'ai' : 'user', null, isAi);
                });

                updateUrlForChatId(sessionId);

                // Close panel
                historyPanel.classList.remove('open');
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }
        } catch (e) {
            console.error('Error restoring session:', e);
        }
    }

    closeRelatedBtn?.addEventListener('click', () => relatedPanel.classList.remove('open'));

    // ── Trace graph renderer ─────────────────────────────────────────────────

    // Panel open / close / refresh
    traceBtn?.addEventListener('click', () => {
        tracePanel.classList.add('open');
        loadTrace();
        // Opened mid-turn (e.g. clicked while a query is still running) — start
        // live polling now instead of waiting for the next sendMessage() call.
        if (isGenerating) startTraceLivePolling();
    });
    closeTraceBtn?.addEventListener('click', () => tracePanel.classList.remove('open'));
    refreshTraceBtn?.addEventListener('click', () => loadTrace());

    // ── Live auto-update ──────────────────────────────────────────────────
    // The backend appends to a shared trace log node-by-node as the LangGraph
    // agent runs (see add_trace() calls in ollamaagent2.py) and clears it right
    // as a new /api/chat request lands (server.py's clear_trace()) — so /api/trace
    // already reflects live, in-progress step data, not just the final result.
    // Polling while a turn is in flight surfaces that instead of requiring a
    // manual Refresh click; it stops itself as soon as the turn finishes.
    let traceLiveInterval = null;
    function startTraceLivePolling() {
        stopTraceLivePolling();
        traceLiveInterval = setInterval(loadTrace, 1200);
    }
    function stopTraceLivePolling() {
        if (traceLiveInterval) {
            clearInterval(traceLiveInterval);
            traceLiveInterval = null;
        }
    }

    // ── "New Query" live label ───────────────────────────────────────────
    // query_manager_node (ollamaagent2.py) only rewrites the user's query
    // when it has chat-history context to fold in, and only then does it
    // add_trace("query_manager", ..., output=<rewritten query>). We poll the
    // same /api/trace endpoint the workflow panel uses to catch that node the
    // moment it appears, and surface it as a friendly line above the answer —
    // on a plain first message (no rewrite) this never fires, so nothing shows.
    let liveNewQueryValue = null;
    let newQueryPollInterval = null;
    let activeNewQueryDiv = null;

    function renderNewQueryLabel() {
        if (!activeNewQueryDiv || !liveNewQueryValue) return;
        activeNewQueryDiv.innerHTML = `Oh, I got it — you're asking: <strong>${escapeHtml(liveNewQueryValue)}</strong>`;
        activeNewQueryDiv.style.display = '';
    }

    function stopNewQueryPolling() {
        if (newQueryPollInterval) {
            clearInterval(newQueryPollInterval);
            newQueryPollInterval = null;
        }
    }

    function startNewQueryPolling() {
        stopNewQueryPolling();
        newQueryPollInterval = setInterval(async () => {
            try {
                const res = await fetch('/api/trace');
                const data = await res.json();
                const steps = data.trace || [];
                const step = steps.find(s => s.node === 'query_manager');
                if (step && step.output) {
                    liveNewQueryValue = step.output;
                    renderNewQueryLabel();
                    stopNewQueryPolling();
                }
            } catch (e) {
                // Non-fatal — the side trace panel's own polling already
                // surfaces connectivity issues; just stop trying this turn.
                stopNewQueryPolling();
            }
        }, 600);
    }

    // ── Live "what's happening" status line ──────────────────────────────
    // Generalizes the New Query mechanism above to every node instead of
    // just query_manager: polls the same /api/trace endpoint and shows a
    // friendly label for whichever node most recently finished, updating
    // live over the course of a turn (Claude/agentic-model style status
    // line) instead of a bare three-dot loader.
    const NODE_STATUS_LABELS = {
        query_rewriter: 'Reading your question…',
        query_manager: 'Connecting this to our earlier chat…',
        check_query_manager: 'Double-checking what you meant…',
        go_duck_search: 'Looking up abbreviations…',
        go_duck_search_verify: 'Verifying abbreviations…',
        keyword_of_post_maker: 'Extracting keywords…',
        keyword_of_post_maker_and_checker: 'Refining keywords…',
        table_selector: 'Choosing the right data tables…',
        sql_judge: 'Validating the query plan…',
        generate_sql: 'Writing the database query…',
        is_safe_sql: 'Running a safety check…',
        execute_sql: 'Querying the database…',
        llm_validator: 'Reviewing the results…',
        content_index_search: 'Searching the knowledge base…',
        neo4j_search: 'Exploring the network graph…',
        fallback_decider: 'Deciding next steps…',
        fallbackchecker: 'Checking coverage…',
        judge_and_reason: 'Reasoning over the findings…',
        answer: 'Drafting the answer…',
        answer_checker: 'Double-checking the answer…',
    };

    let statusPollInterval = null;
    let activeStatusDiv = null;

    function renderStatusLine(node) {
        if (!activeStatusDiv) return;
        const label = NODE_STATUS_LABELS[node] || 'Thinking…';
        activeStatusDiv.textContent = label;
    }

    function stopStatusPolling() {
        if (statusPollInterval) {
            clearInterval(statusPollInterval);
            statusPollInterval = null;
        }
    }

    function startStatusPolling() {
        stopStatusPolling();
        let lastNode = null;
        statusPollInterval = setInterval(async () => {
            try {
                const res = await fetch('/api/trace');
                const data = await res.json();
                const steps = data.trace || [];
                if (!steps.length) return;
                // Most recently completed node — the one whose work is
                // "currently happening" from the user's point of view.
                const latest = steps[steps.length - 1];
                if (latest.node !== lastNode) {
                    lastNode = latest.node;
                    renderStatusLine(latest.node);
                }
            } catch (e) {
                // Non-fatal — same reasoning as startNewQueryPolling above.
                stopStatusPolling();
            }
        }, 500);
    }

    // Node-type classification: maps known node names → category
    const TRACE_NODE_TYPES = {
        query_rewriter: 'core', router: 'core', merge: 'core',
        judge_and_reason: 'core', answer: 'core',
        table_selector_and_decider: 'sql', table_selector: 'sql',
        value_grounding: 'sql', build_sql: 'sql',
        execute_sql: 'sql', llm_validator: 'sql',
        sql_judge_matches: 'safety', safe_sql: 'safety',
        sql_column_validator: 'safety',
        build_qdrant_query: 'qdrant', qdrant_search: 'qdrant',
        pdf_search: 'pdf', pdf_answer: 'pdf',
    };

    const TRACE_TYPE_META = {
        core:    { stroke: '#4f8ef7', fill: '#1e3a5f',  text: '#93c5fd',  badge: 'Core',    emoji: '⚙️',  arrow: 'tg-arrow-blue'   },
        sql:     { stroke: '#10b981', fill: '#064e3b',  text: '#6ee7b7',  badge: 'SQL',     emoji: '🗄️',  arrow: 'tg-arrow-green'  },
        safety:  { stroke: '#ef4444', fill: '#450a0a',  text: '#fca5a5',  badge: 'Safety',  emoji: '🔒',  arrow: 'tg-arrow-red'    },
        qdrant:  { stroke: '#8b5cf6', fill: '#2e1065',  text: '#a78bfa',  badge: 'Qdrant',  emoji: '🔮',  arrow: 'tg-arrow-purple' },
        pdf:     { stroke: '#f59e0b', fill: '#451a03',  text: '#fcd34d',  badge: 'PDF',     emoji: '📄',  arrow: 'tg-arrow-amber'  },
        unknown: { stroke: '#475569', fill: '#1e293b',  text: '#94a3b8',  badge: '?',       emoji: '🔘',  arrow: 'tg-arrow-gray'   },
    };

    const NODE_W = 360, NODE_H = 52, NODE_RX = 13;
    const NODE_GAP_Y = 88;   // vertical spacing between node centres
    const SVG_PADX = 20, SVG_PADY = 28;

    function _traceNodeType(name) {
        return TRACE_NODE_TYPES[name] || 'unknown';
    }

    function _buildTraceSVG(steps) {
        const total  = steps.length;
        const svgH   = SVG_PADY * 2 + total * NODE_GAP_Y + (NODE_H - NODE_GAP_Y);
        const svgW   = SVG_PADX * 2 + NODE_W;
        const cx     = svgW / 2;

        // Arrow marker defs
        const arrowColours = {
            'tg-arrow-blue':   '#4f8ef7',
            'tg-arrow-green':  '#10b981',
            'tg-arrow-red':    '#ef4444',
            'tg-arrow-purple': '#8b5cf6',
            'tg-arrow-amber':  '#f59e0b',
            'tg-arrow-gray':   '#475569',
        };

        let defs = `<defs>
          <filter id="tg-glow"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <pattern id="tg-grid" width="24" height="24" patternUnits="userSpaceOnUse">
            <path d="M 24 0 L 0 0 0 24" fill="none" stroke="#111827" stroke-width="0.5"/>
          </pattern>`;
        for (const [id, col] of Object.entries(arrowColours)) {
            defs += `<marker id="${id}" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="${col}"/>
            </marker>`;
        }
        defs += '</defs>';

        // Background
        let body = `<rect width="${svgW}" height="${svgH}" fill="#0a0d14"/>
                    <rect width="${svgW}" height="${svgH}" fill="url(#tg-grid)"/>`;

        // START circle
        const startCY = SVG_PADY - 10;
        body += `<circle cx="${cx}" cy="${startCY}" r="16" fill="#1e3a5f" stroke="#4f8ef7" stroke-width="1.8"/>
                 <text x="${cx}" y="${startCY + 4}" fill="#60a5fa" font-size="10" font-weight="700"
                       font-family="Inter,sans-serif" text-anchor="middle">START</text>`;

        steps.forEach((step, i) => {
            const type = _traceNodeType(step.node || '');
            const meta = TRACE_TYPE_META[type];
            const nodeX = SVG_PADX;
            const nodeCY = SVG_PADY + i * NODE_GAP_Y + NODE_GAP_Y / 2 + 8;
            const nodeY  = nodeCY - NODE_H / 2;
            const label  = (step.node || 'unknown').replace(/_/g, '_\u200B'); // allow soft wrap

            // Connector from previous element (start or previous node)
            const prevCY = i === 0
                ? startCY + 16
                : SVG_PADY + (i - 1) * NODE_GAP_Y + NODE_GAP_Y / 2 + 8 + NODE_H / 2;
            const lineX = cx;
            body += `<line x1="${lineX}" y1="${prevCY}" x2="${lineX}" y2="${nodeY + 2}"
                       stroke="${meta.stroke}" stroke-width="1.8"
                       stroke-dasharray="6,3"
                       marker-end="url(#${meta.arrow})"
                       class="tg-edge-animated" opacity="0.7"/>`;

            // Node rect (clickable)
            body += `<g class="tg-node" data-idx="${i}" role="button" tabindex="0">
              <rect x="${nodeX}" y="${nodeY}" width="${NODE_W}" height="${NODE_H}" rx="${NODE_RX}"
                    fill="${meta.fill}" stroke="${meta.stroke}" stroke-width="1.8"/>
              <!-- Order badge circle -->
              <circle cx="${nodeX + 22}" cy="${nodeCY}" r="13"
                      fill="${meta.stroke}" opacity="0.18"/>
              <text x="${nodeX + 22}" y="${nodeCY + 4}" fill="${meta.stroke}" font-size="11"
                    font-weight="700" font-family="Inter,sans-serif" text-anchor="middle">${i + 1}</text>
              <!-- Node name -->
              <text x="${nodeX + 44}" y="${nodeCY - 7}" fill="${meta.text}" font-size="12.5"
                    font-weight="700" font-family="Inter,sans-serif" dominant-baseline="middle">${escapeHtml(step.node || 'unknown')}</text>
              <!-- Sub-label -->
              <text x="${nodeX + 44}" y="${nodeCY + 10}" fill="#64748b" font-size="10.5"
                    font-family="Inter,sans-serif" dominant-baseline="middle">${meta.badge} · step ${i + 1}</text>
              <!-- Click caret -->
              <text x="${nodeX + NODE_W - 14}" y="${nodeCY + 4}" fill="${meta.stroke}"
                    font-size="13" text-anchor="middle" opacity="0.7">›</text>
            </g>`;
        });

        // END circle
        const lastNodeCY = SVG_PADY + (total - 1) * NODE_GAP_Y + NODE_GAP_Y / 2 + 8 + NODE_H / 2;
        const endCY = svgH - SVG_PADY + 6;
        body += `<line x1="${cx}" y1="${lastNodeCY}" x2="${cx}" y2="${endCY - 16}"
                   stroke="#10b981" stroke-width="1.8" marker-end="url(#tg-arrow-green)" opacity="0.7"/>
                 <circle cx="${cx}" cy="${endCY}" r="16" fill="#0f2028" stroke="#10b981" stroke-width="1.8"/>
                 <text x="${cx}" y="${endCY + 4}" fill="#6ee7b7" font-size="10" font-weight="700"
                       font-family="Inter,sans-serif" text-anchor="middle">END</text>`;

        return { svg: `${defs}${body}`, width: svgW, height: svgH };
    }

    function _openTraceDrawer(step, idx) {
        const type = _traceNodeType(step.node || '');
        const meta = TRACE_TYPE_META[type];

        document.getElementById('traceDrawerEmoji').textContent = meta.emoji;
        document.getElementById('traceDrawerName').textContent  = step.node || 'unknown';

        const badge = document.getElementById('traceDrawerBadge');
        badge.textContent  = meta.badge;
        badge.className    = `trace-drawer-badge badge-${type}`;

        let bodyHtml = '';
        if (step.user_query) {
            bodyHtml += `<div class="trace-drawer-section">
              <div class="trace-drawer-label">User Query</div>
              <div class="trace-drawer-value">${escapeHtml(step.user_query)}</div>
            </div>`;
        }
        // retry_count is the SQL-planning loop's attempt number (1, 2, 3…) —
        // set on every node inside that loop (table_selector_and_decider →
        // build_sql → sql_judge_matches → safe_sql → sql_column_validator →
        // execute_sql → judge_and_reason). Mirrors the server's own
        // "🔄 Graph execution loop count" stdout log, but per-node in the UI.
        if (step.retry_count !== null && step.retry_count !== undefined) {
            bodyHtml += `<div class="trace-drawer-section">
              <div class="trace-drawer-label">Graph Execution Loop</div>
              <div class="trace-drawer-value">🔄 Loop count: ${step.retry_count}</div>
            </div>`;
        }
        if (step.prompt) {
            bodyHtml += `<div class="trace-drawer-section">
              <div class="trace-drawer-label">Prompt / Input</div>
              <div class="trace-drawer-value">${escapeHtml(step.prompt)}</div>
            </div>`;
        }
        if (step.output) {
            bodyHtml += `<div class="trace-drawer-section">
              <div class="trace-drawer-label">Output</div>
              <div class="trace-drawer-value">${escapeHtml(step.output)}</div>
            </div>`;
        }
        if (!bodyHtml) {
            bodyHtml = `<div class="trace-drawer-section" style="color:#475569;font-size:12px;">No prompt/output captured for this node.</div>`;
        }
        document.getElementById('traceDrawerBody').innerHTML = bodyHtml;
        document.getElementById('traceDetailDrawer').classList.add('open');

        if (window.lucide) lucide.createIcons();
    }

    async function loadTrace() {
        if (!traceList) return;
        try {
            const res   = await fetch('/api/trace');
            const data  = await res.json();
            const steps = data.trace || [];

            const counter = document.getElementById('traceStepCounter');
            const drawer  = document.getElementById('traceDetailDrawer');

            if (!steps.length) {
                traceList.innerHTML = '<div class="trace-panel-empty">Ask a question to see the agent\'s workflow graph.</div>';
                if (counter) counter.style.display = 'none';
                if (drawer)  drawer.classList.remove('open');
                return;
            }

            // Show step counter
            if (counter) {
                counter.style.display = 'flex';
                document.getElementById('traceStepCount').textContent = steps.length;
            }

            // Build SVG
            const { svg, width, height } = _buildTraceSVG(steps);
            traceList.innerHTML = `
              <div class="trace-graph-wrap">
                <svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg"
                     style="height:${height}px">${svg}</svg>
              </div>`;

            // Tooltip
            const tooltip = document.getElementById('traceTooltip');

            // Wire node interactions
            traceList.querySelectorAll('.tg-node').forEach(g => {
                const idx  = parseInt(g.dataset.idx, 10);
                const step = steps[idx];
                const type = _traceNodeType(step.node || '');
                const meta = TRACE_TYPE_META[type];

                g.addEventListener('mouseenter', e => {
                    const hasLoop = step.retry_count !== null && step.retry_count !== undefined;
                    tooltip.innerHTML = `<strong>${meta.emoji} ${escapeHtml(step.node || 'unknown')}</strong>${meta.badge} · step ${idx + 1}${hasLoop ? ' · 🔄 loop ' + step.retry_count : ''}${step.user_query ? '<br><span style="color:#94a3b8;font-size:11px;">' + escapeHtml(step.user_query.slice(0, 80)) + (step.user_query.length > 80 ? '…' : '') + '</span>' : ''}`;
                    tooltip.classList.add('show');
                });

                g.addEventListener('mousemove', e => {
                    let x = e.clientX + 14, y = e.clientY + 14;
                    if (x + 320 > window.innerWidth)  x = e.clientX - 320;
                    if (y + 100 > window.innerHeight)  y = e.clientY - 100;
                    tooltip.style.left = x + 'px';
                    tooltip.style.top  = y + 'px';
                });

                g.addEventListener('mouseleave', () => tooltip.classList.remove('show'));

                g.addEventListener('click', () => {
                    traceList.querySelectorAll('.tg-node').forEach(n => n.classList.remove('tg-active'));
                    g.classList.add('tg-active');
                    _openTraceDrawer(step, idx);
                });

                // Keyboard
                g.addEventListener('keydown', e => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        g.click();
                    }
                });
            });

            // Drawer close button
            const drawerClose = document.getElementById('traceDrawerClose');
            if (drawerClose) {
                drawerClose.onclick = () => {
                    document.getElementById('traceDetailDrawer').classList.remove('open');
                    traceList.querySelectorAll('.tg-node').forEach(n => n.classList.remove('tg-active'));
                };
            }

        } catch (error) {
            console.error('Trace load error:', error);
            traceList.innerHTML = '<div class="trace-panel-empty">Couldn\'t load the workflow graph.</div>';
        }
    }


    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str ?? '';
        return div.innerHTML;
    }

    // Fetches related links/topics for the given query and renders them into
    // the right-side panel. Runs independently of the chat request so a slow
    // or failed lookup never blocks the actual answer.
    async function loadRelatedLinks(query) {
        relatedPanel.classList.add('open');
        relatedList.innerHTML = '<div class="related-panel-loading">Searching related links...</div>';

        try {
            const res = await fetch(`/api/related-links?query=${encodeURIComponent(query)}`);
            const data = await res.json();
            const links = data.links || [];

            if (!links.length) {
                relatedList.innerHTML = '<div class="related-panel-empty">No related links found.</div>';
                return;
            }

            relatedList.innerHTML = links.map(link => `
                <a class="related-link-card" href="${escapeHtml(link.url)}" target="_blank" rel="noopener noreferrer">
                    <div class="related-link-title">${escapeHtml(link.title)}</div>
                    <div class="related-link-url">${escapeHtml(link.url)}</div>
                    ${link.snippet ? `<div class="related-link-snippet">${escapeHtml(link.snippet)}</div>` : ''}
                </a>
            `).join('');
        } catch (error) {
            console.error('Related links error:', error);
            relatedList.innerHTML = '<div class="related-panel-empty">Couldn\'t load related links.</div>';
        }
    }

    async function sendMessage(options = {}) {
        if (isGenerating) return;
        const text = options.overrideText ?? userInput.value.trim();
        if (!text) return;
        
        // Clear previous SQL results state for the new query
        window._lastSQLIds = [];
        window._lastChatQuery = text;

        // Fresh turn — reset the "New Query" live label state
        liveNewQueryValue = null;
        activeNewQueryDiv = null;
        stopNewQueryPolling();

        // Switch layout to chat mode if first message
        if (!contentWrapper.classList.contains('chat-active')) {
            contentWrapper.classList.add('chat-active');
        }

        // Add user message
        addMessage(options.displayText || text, 'user');

        // Fire-and-forget: populate the related-links panel without blocking the answer
        // (unless the user has turned this off in Settings)
        if (window.settingsManager?.isRelatedLinksEnabled() ?? true) {
            loadRelatedLinks(text);
        }

        // Clear input and collapse it back to a single line
        userInput.value = '';
        autoResizeInput();

        // Lock the UI: disable input, show the stop button
        setGeneratingState(true);

        // Scroll to bottom
        chatContainer.scrollTop = chatContainer.scrollHeight;

        // Add animated typing/loader indicator
        const typingId = 'typing-' + Date.now();
        showTypingIndicator(typingId);
        chatContainer.scrollTop = chatContainer.scrollHeight;

        currentController = new AbortController();

        // Reset the panel to empty right away and start polling — the server
        // clears its trace log the instant /api/chat lands, so an open (or
        // later-opened) Agent Workflow panel fills in live as each node runs.
        if (traceList) traceList.innerHTML = '<div class="trace-panel-empty">Ask a question to see the agent\'s workflow graph.</div>';
        startTraceLivePolling();

        if (twoWayChatActive) {
            // Let the user interrupt while the request is still
            // processing/streaming, not only once the reply starts being
            // spoken — abort this request the moment new speech is heard.
            // The mic starts listening again right now (not after the
            // reply is ready) so it's actually available to catch that.
            const requestController = currentController;
            activeTurnInterrupt = () => {
                console.debug('[2-Way] Barge-in during processing — aborting in-flight request.');
                requestController.abort();
            };
            startTwoWayListening();
        }

        // When a PDF "expert" avatar is active, scope this turn's PDF
        // retrieval to only that expert's file(s) instead of every PDF
        // uploaded this session, and tell the backend which persona to
        // answer as (see avatar widget module).
        const activePdfScope = window.getActivePdfScope ? window.getActivePdfScope() : null;
        const activeExpertName = window.getActiveExpertName ? window.getActiveExpertName() : null;
        const currentLang = window.i18n?.getLanguage() || 'en';

        try {
            // Call FastAPI backend
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    query: text,
                    limit: currentLimit,
                    chat_id: currentChatId,
                    ...(activePdfScope ? { pdf_scope: activePdfScope } : {}),
                    ...(activeExpertName ? { expert_name: activeExpertName } : {}),
                    ...(options.reportSelection ? { report_selection: options.reportSelection } : {}),
                    ...(options.endpointWriteConfirmation ? { endpoint_write_confirmation: options.endpointWriteConfirmation } : {}),
                    ...(options.endpointMultiSelection ? { endpoint_multi_selection: options.endpointMultiSelection } : {}),
                    ...(options.endpointMultiSelectionQuery ? { endpoint_multi_selection_query: options.endpointMultiSelectionQuery } : {}),
                    // Every call site defaults to 'text' (typing, buttons, programmatic
                    // sendMessage() calls); only the two ASR auto-submit paths above
                    // pass inputSource: 'voice' explicitly.
                    input_source: options.inputSource || 'text',
                    lang: currentLang
                }),
                signal: currentController.signal
            });

            if (!response.ok || !response.body) throw new Error('Network response was not ok');

            // Reflect this conversation's chat_id in the address bar
            // (ChatGPT-style /c/<chat_id>) — server tells us which one this
            // turn was saved under via the X-Chat-Id header. Same value on
            // every turn of the same chat, so this only actually changes the
            // URL on the first message of a new one.
            updateUrlForChatId(response.headers.get('X-Chat-Id'));

            // First bytes are in: swap the dot loader for a live message we stream text into
            const typingMsg = document.getElementById(typingId);
            if (typingMsg) typingMsg.remove();

            await streamAssistantMessage(response.body, currentController.signal);

        } catch (error) {
            const typingMsg = document.getElementById(typingId);
            if (typingMsg) typingMsg.remove();

            if (error.name !== 'AbortError') {
                console.error('Error:', error);
                addMessage('Sorry, I encountered an error connecting to the server.', 'ai');
            }
        } finally {
            currentController = null;
            setGeneratingState(false);
            chatContainer.scrollTop = chatContainer.scrollHeight;
            // Stop live polling and pull this turn's final LangGraph node trace
            // (one last fetch in case the turn finished between poll ticks) so
            // the Agent Workflow panel is ready to show if/when the user opens it.
            stopTraceLivePolling();
            stopNewQueryPolling();
            stopStatusPolling();
            activeStatusDiv = null;
            loadTrace();
        }
    }

    // Animated "..." replacement: three bouncing dots shown while the server prepares a response
    function showTypingIndicator(id) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message ai';
        msgDiv.id = id;

        // Live "what's happening" line — updates as each LangGraph node
        // finishes (see startStatusPolling above). Starts on "Thinking…"
        // before the first trace step lands. This is now the ONLY loading
        // indicator shown while waiting for a response — the old three-dot
        // bouncing loader has been removed in favor of this.
        const statusDiv = document.createElement('div');
        statusDiv.className = 'agent-status-line';
        statusDiv.textContent = 'Thinking…';
        msgDiv.appendChild(statusDiv);
        activeStatusDiv = statusDiv;
        startStatusPolling();

        // Sibling of contentDiv (not inside it) so contentDiv's later
        // innerHTML rewrites never wipe this out. Hidden until a
        // query_manager trace step actually shows up (see startNewQueryPolling).
        const newQueryDiv = document.createElement('div');
        newQueryDiv.className = 'new-query-label';
        newQueryDiv.style.display = 'none';
        msgDiv.appendChild(newQueryDiv);
        activeNewQueryDiv = newQueryDiv;
        startNewQueryPolling();

        messagesDiv.appendChild(msgDiv);
    }

    // Reads the /api/chat response body as it streams in and renders it live,
    // word by word, with a blinking cursor — the actual text-streaming/typewriter effect.
    async function streamAssistantMessage(body, signal) {
        const reader = body.getReader();
        const decoder = new TextDecoder();

        const msgDiv = document.createElement('div');
        msgDiv.className = 'message ai';

        // Carries the "New Query" label over from the typing indicator (or
        // picks it up here if query_manager finished before streaming started,
        // which is the common case since it runs early in the graph).
        const newQueryDiv = document.createElement('div');
        newQueryDiv.className = 'new-query-label';
        newQueryDiv.style.display = 'none';
        msgDiv.appendChild(newQueryDiv);
        activeNewQueryDiv = newQueryDiv;
        renderNewQueryLabel();

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content streaming';
        contentDiv.innerHTML = '<span class="stream-cursor"></span>';

        msgDiv.appendChild(contentDiv);
        messagesDiv.appendChild(msgDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;

        let accumulated = '';
        let aborted = false;

        try {
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                accumulated += decoder.decode(value, { stream: true });
                let displayHtml = accumulated;
                const streamMetaIdx = displayHtml.indexOf('__META__');
                if (streamMetaIdx !== -1) {
                    displayHtml = displayHtml.substring(0, streamMetaIdx);
                }
                contentDiv.innerHTML = marked.parse(displayHtml) + '<span class="stream-cursor"></span>';
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }
        } catch (error) {
            if (error.name === 'AbortError' || signal.aborted) {
                aborted = true;
            } else {
                throw error;
            }
        }

        contentDiv.classList.remove('streaming');

        if (!accumulated.trim()) {
            contentDiv.textContent = aborted ? 'Stopped generating.' : 'Sorry, I encountered an error connecting to the server.';
            return;
        }

        let metaData = null;
        const metaIdx = accumulated.indexOf('__META__');
        if (metaIdx !== -1) {
            const endIdx = accumulated.indexOf('__END_META__', metaIdx);
            if (endIdx !== -1) {
                const jsonStr = accumulated.substring(metaIdx + 8, endIdx);
                try {
                    metaData = JSON.parse(jsonStr);
                } catch(e) { console.error('Error parsing meta', e); }
            }
            accumulated = accumulated.substring(0, metaIdx).trim();
        }

        // Final clean render (no cursor) + chart/graph parsing + Listen action button
        contentDiv.innerHTML = marked.parse(accumulated);
        
        if (metaData && metaData.sql_rows !== undefined) {
            const countDiv = document.createElement('div');
            countDiv.style.cssText = "display: inline-block; margin-top: 10px; padding: 4px 10px; background-color: var(--panel-bg, #f3f4f6); border: 1px solid var(--border-color, #e5e7eb); border-radius: 12px; font-size: 12px; color: var(--text-secondary, #6b7280);";
            countDiv.innerHTML = `<i data-lucide="search" style="width:14px;height:14px;vertical-align:-2px;margin-right:4px;"></i>Found ${metaData.sql_rows} matching posts`;
            contentDiv.appendChild(countDiv);
            
            // Store globally for feed
            window._lastSQLIds = metaData.sql_ids || [];

            // "Show more" — fetches the NEXT batch of rows for this same SQL
            // query directly (see POST /api/chat/more in server.py). This
            // does NOT re-run the LangGraph agent or call any LLM: it reuses
            // the exact executed SQL and advances OFFSET, so it's fast and
            // returns real additional rows rather than a re-summarized
            // answer capped to the first ~20 rows. Only shown when the
            // answer's own text likely didn't already enumerate everything
            // (i.e. when there's more data than a typical single answer lists).
            if (metaData.sql_rows > 10 && currentChatId) {
                appendShowMoreButton(contentDiv, currentChatId);
            }
            
            if (metaData.sql_rows > 20 && window.settingsManager && window.settingsManager.isVizWithChatEnabled()) {
                const networkBtn = document.getElementById('networkBtn');
                if (networkBtn && !document.getElementById('networkPanel').classList.contains('open')) {
                    networkBtn.click();
                }
                const feedBtn = document.getElementById('feedBtn');
                if (feedBtn && !document.getElementById('feedPanel').classList.contains('open')) {
                    feedBtn.click();
                }
                // Visualize the exact posts this answer resolved to (metaData.sql_ids),
                // not a fresh independent search — an independent /network/agent search
                // on leftover keywords from the question can return a completely
                // different, unrelated set of results than the ones actually being
                // discussed in the chat answer.
                setTimeout(() => {
                    if (window.loadSQLTopicChart) {
                        window.loadSQLTopicChart(metaData.sql_ids || []);
                    }
                }, 300);
            }
        }

        renderChartsAndGraphs(contentDiv);
        addListenButton(msgDiv, contentDiv);

        if (twoWayChatActive) {
            // The mic has already been listening continuously since
            // sendMessage kicked this turn off (see there), through both
            // processing and now the reply being spoken, so the user can
            // barge in at any point in the turn. This call is just a
            // safety net in case it somehow isn't already running.
            // recognition.onresult's barge-in check stops the speech the
            // moment it sees real speech come in; if the user stays silent,
            // the reply just finishes normally and the mic (already
            // listening) keeps waiting for the next thing.
            // Note: relies on the browser's mic echo cancellation to avoid
            // picking up the assistant's own voice as a false barge-in —
            // most reliable with headphones or the OS's own AEC.
            startTwoWayListening();
            await speakAnswerForTwoWay(accumulated);
        } else if (window.avatarSpeakIfActive) {
            // Normal mode, unchanged: if the avatar widget is open, have it
            // speak this same answer, fire-and-forget — the widget reuses
            // this text input instead of its own mic.
            window.avatarSpeakIfActive(accumulated);
        }
    }

    // Appends a "Show more" button under an answer's result-count badge.
    // Clicking it calls POST /api/chat/more, which re-executes the SAME SQL
    // with the OFFSET advanced (no LLM call, no LangGraph re-run) and returns
    // the next batch of raw rows formatted as plain text — appended directly
    // under the existing answer rather than starting a whole new chat turn.
    function appendShowMoreButton(contentDiv, chatId) {
        const btn = document.createElement('button');
        btn.textContent = 'Show more';
        btn.style.cssText = "display: block; margin-top: 10px; padding: 6px 14px; background-color: var(--accent-color, #4f8ef7); color: #fff; border: none; border-radius: 8px; font-size: 13px; cursor: pointer;";

        btn.addEventListener('click', async () => {
            btn.disabled = true;
            btn.textContent = 'Loading…';
            try {
                const res = await fetch('/api/chat/more', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ chat_id: chatId }),
                });
                const data = await res.json();

                if (!res.ok || data.error) {
                    btn.textContent = data.error || 'Failed to load more.';
                    return;
                }
                if (!data.rows_returned) {
                    btn.textContent = 'No more results';
                    btn.disabled = true;
                    return;
                }

                const moreDiv = document.createElement('div');
                moreDiv.style.cssText = "margin-top: 10px; white-space: pre-wrap; font-size: 14px;";
                moreDiv.innerHTML = marked.parse(data.text || '');
                btn.insertAdjacentElement('beforebegin', moreDiv);

                if (data.has_more) {
                    btn.disabled = false;
                    btn.textContent = 'Show more';
                } else {
                    btn.textContent = 'No more results';
                    btn.disabled = true;
                }
            } catch (e) {
                console.error('Error loading more results', e);
                btn.textContent = 'Failed to load more.';
            }
        });

        contentDiv.appendChild(btn);
    }

    // Attaches the "Listen to response" speech-synthesis button to an AI message
    function addListenButton(msgDiv, contentDiv) {
        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'message-actions';

        const listenBtn = document.createElement('button');
        listenBtn.className = 'listen-btn';
        listenBtn.title = 'Listen to response';
        listenBtn.innerHTML = '<i data-lucide="volume-2"></i>';

        listenBtn.onclick = async () => {
            const wasSpeaking = listenBtn.dataset.speaking === 'true';
            stopElevenLabsAudio();
            if (window.speechSynthesis.speaking) window.speechSynthesis.cancel();

            // Reset all buttons (including this one) to idle first.
            document.querySelectorAll('.listen-btn').forEach(btn => {
                btn.dataset.speaking = 'false';
                btn.innerHTML = '<i data-lucide="volume-2"></i>';
            });
            if (window.lucide) window.lucide.createIcons();

            // Second click on the button that was already speaking = stop, don't restart.
            if (wasSpeaking) return;

            const setSpeakingIcon = () => {
                listenBtn.dataset.speaking = 'true';
                listenBtn.innerHTML = '<i data-lucide="square"></i>';
                if (window.lucide) window.lucide.createIcons();
            };
            const resetIcon = () => {
                listenBtn.dataset.speaking = 'false';
                listenBtn.innerHTML = '<i data-lucide="volume-2"></i>';
                if (window.lucide) window.lucide.createIcons();
            };

            // "output is <answer>", punctuation stripped (see
            // buildChatSpokenText above).
            const textToRead = buildChatSpokenText(contentDiv.innerText || contentDiv.textContent);

            setSpeakingIcon();

            const audio = await fetchElevenLabsAudio(textToRead);
            // The user may have clicked stop (or another listen button) while the fetch was in flight.
            if (listenBtn.dataset.speaking !== 'true') { stopElevenLabsAudio(); return; }

            if (audio) {
                currentElevenLabsAudio = audio;
                currentElevenLabsAudioUrl = audio.src;
                audio.onended = () => { stopElevenLabsAudio(); resetIcon(); };
                audio.onerror = () => { stopElevenLabsAudio(); speakWithBrowserTts(textToRead, { onend: resetIcon, onerror: resetIcon }); };
                audio.play().catch(() => { stopElevenLabsAudio(); speakWithBrowserTts(textToRead, { onend: resetIcon, onerror: resetIcon }); });
            } else {
                speakWithBrowserTts(textToRead, { onend: resetIcon, onerror: resetIcon });
            }
        };

        actionsDiv.appendChild(listenBtn);

        // Like/Dislike — hidden unless explicitly turned on in Settings
        // (window.settingsManager.isLikeDislikeEnabled(), default off).
        // Purely a visual selection for now (mutually exclusive toggle);
        // not sent anywhere — just an in-UI reaction.
        if (window.settingsManager?.isLikeDislikeEnabled?.()) {
            const likeBtn = document.createElement('button');
            likeBtn.className = 'feedback-btn like-btn';
            likeBtn.title = 'Good response';
            likeBtn.innerHTML = '<i data-lucide="thumbs-up"></i>';

            const dislikeBtn = document.createElement('button');
            dislikeBtn.className = 'feedback-btn dislike-btn';
            dislikeBtn.title = 'Bad response';
            dislikeBtn.innerHTML = '<i data-lucide="thumbs-down"></i>';

            likeBtn.onclick = () => {
                const nowActive = !likeBtn.classList.contains('active');
                likeBtn.classList.toggle('active', nowActive);
                dislikeBtn.classList.remove('active');
            };
            dislikeBtn.onclick = () => {
                const nowActive = !dislikeBtn.classList.contains('active');
                dislikeBtn.classList.toggle('active', nowActive);
                likeBtn.classList.remove('active');
            };

            actionsDiv.appendChild(likeBtn);
            actionsDiv.appendChild(dislikeBtn);
        }

        msgDiv.appendChild(actionsDiv);

        if (window.lucide) {
            window.lucide.createIcons();
        }
    }

    // Detects ```json chart/graph code blocks inside an AI message and renders them as D3 visuals
    function renderChartsAndGraphs(contentDiv) {
        const codeBlocks = contentDiv.querySelectorAll('pre code.language-json');
        codeBlocks.forEach(block => {
            try {
                const data = JSON.parse(block.textContent);
                if (data.type === 'bar' && Array.isArray(data.data)) {
                    const chartDiv = document.createElement('div');
                    chartDiv.className = 'chart-container';

                    const preElement = block.parentElement;
                    preElement.parentNode.replaceChild(chartDiv, preElement);

                    renderBarChart(chartDiv, data.data);
                } else if (data.type === 'graph' && Array.isArray(data.nodes) && Array.isArray(data.links)) {
                    const graphDiv = document.createElement('div');
                    graphDiv.id = 'network-graph-container';
                    graphDiv.className = 'network-graph-container';
                    graphDiv.style.width = '100%';
                    graphDiv.style.height = '400px';
                    graphDiv.style.position = 'relative';
                    graphDiv.style.borderRadius = '12px';
                    graphDiv.style.overflow = 'hidden';
                    graphDiv.style.marginTop = '10px';

                    const preElement = block.parentElement;
                    preElement.parentNode.replaceChild(graphDiv, preElement);

                    if (window.buildNetworkGraph) {
                        window.buildNetworkGraph(data);
                    }
                } else if (data.type === 'report_picker' && (data.topic || data.trending)) {
                    const preElement = block.parentElement;
                    preElement.parentNode.replaceChild(buildReportPickerCard(data), preElement);
                } else if (data.type === 'adhoc_report_preview' && data.template_id) {
                    const preElement = block.parentElement;
                    preElement.parentNode.replaceChild(buildAdhocReportPreviewCard(data), preElement);
                } else if (data.type === 'endpoint_write_confirmation' && data.endpoint) {
                    const preElement = block.parentElement;
                    preElement.parentNode.replaceChild(buildEndpointWriteConfirmationCard(data), preElement);
                } else if (data.type === 'endpoint_multi_selection' && Array.isArray(data.candidates)) {
                    const preElement = block.parentElement;
                    preElement.parentNode.replaceChild(buildEndpointMultiSelectionCard(data), preElement);
                }
            } catch (e) {
                console.error("Error parsing potential chart/graph JSON:", e);
            }
        });
    }

    // Builds the interactive report-component picker card sent by
    // dynamic_report_maker_node (see ollamaagent2.py's llm_validator_node).
    // `data` = {report_id, topic_id, topic_title, catalog, suggested}.
    // On "Generate report", the confirmed selection is echoed straight back
    // to the server as `report_selection` on the very next request — there's
    // no server-side memory of this card between turns, so this payload IS
    // the memory (see the note in ollamaagent2.py's query_rewriter_node).
    // Builds one report type's checkbox list (topic or trending). Returns
    // the container element plus refs to its (non-disabled) checkboxes so
    // the caller can read which are checked and toggle visibility.
    function _buildReportComponentChecklist(catalog, suggested) {
        const container = document.createElement('div');
        container.className = 'report-picker-checklist';
        const suggestedSet = new Set(suggested || []);
        const checkboxRefs = [];

        (catalog || []).forEach(comp => {
            const isComingSoon = comp.v1 === false;
            const row = document.createElement('label');
            row.className = 'report-picker-option' + (isComingSoon ? ' disabled' : '');

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = comp.id;
            cb.checked = !isComingSoon && suggestedSet.has(comp.id);
            cb.disabled = isComingSoon;
            row.appendChild(cb);

            const txt = document.createElement('span');
            txt.className = 'report-picker-option-text';
            const label = document.createElement('strong');
            label.textContent = comp.title || comp.label || comp.id;
            const desc = document.createElement('span');
            desc.textContent = (comp.description || '') + (isComingSoon ? ' (coming soon)' : '');
            txt.appendChild(label);
            txt.appendChild(desc);
            row.appendChild(txt);

            container.appendChild(row);
            if (!isComingSoon) checkboxRefs.push(cb);
        });

        return { container, checkboxRefs };
    }

    // data = {report_id, topic_title, default_report_type, topic:{available,
    // topics, catalog, suggested}, trending:{available, date_range, catalog,
    // suggested}} — see ollamaagent2.py's dynamic_report_maker block.
    function buildReportPickerCard(data) {
        const card = document.createElement('div');
        card.className = 'chart-container report-picker-card';

        const title = document.createElement('div');
        title.className = 'report-picker-title';
        title.textContent = `📄 Build a report — "${data.topic_title || 'this'}"`;
        card.appendChild(title);

        // Report-type selector — two radios in one card, no extra round
        // trip. Switching the radio swaps which checklist is visible below;
        // the confirmed report_type + matching payload shape is only sent
        // once "Generate report" is clicked.
        const typeRow = document.createElement('div');
        typeRow.className = 'report-picker-type-row';

        const topicInfo = data.topic || { available: false, topics: [], catalog: [], suggested: [] };
        const trendingInfo = data.trending || { available: true, date_range: {}, catalog: [], suggested: [] };
        const defaultType = data.default_report_type === 'topic' && topicInfo.available ? 'topic' : 'trending';

        const makeRadio = (value, label, disabled) => {
            const optLabel = document.createElement('label');
            optLabel.className = 'report-picker-type-option' + (disabled ? ' disabled' : '');
            const radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = `report-type-${data.report_id}`;
            radio.value = value;
            radio.checked = defaultType === value;
            radio.disabled = disabled;
            optLabel.appendChild(radio);
            optLabel.appendChild(document.createTextNode(' ' + label));
            typeRow.appendChild(optLabel);
            return radio;
        };
        const trendingRadio = makeRadio('trending', 'Trending Report (aggregate, date range)', !trendingInfo.available);
        const topicRadio = makeRadio('topic', 'Topic Report (this topic, full breakdown)', !topicInfo.available);
        card.appendChild(typeRow);

        const trendingList = _buildReportComponentChecklist(trendingInfo.catalog, trendingInfo.suggested);
        const topicList = _buildReportComponentChecklist(topicInfo.catalog, topicInfo.suggested);
        topicList.container.style.display = defaultType === 'topic' ? '' : 'none';
        trendingList.container.style.display = defaultType === 'trending' ? '' : 'none';
        card.appendChild(trendingList.container);
        card.appendChild(topicList.container);

        const syncVisibleChecklist = () => {
            const isTopic = topicRadio.checked;
            topicList.container.style.display = isTopic ? '' : 'none';
            trendingList.container.style.display = isTopic ? 'none' : '';
        };
        trendingRadio.onchange = syncVisibleChecklist;
        topicRadio.onchange = syncVisibleChecklist;

        const customInput = document.createElement('input');
        customInput.type = 'text';
        customInput.className = 'report-picker-custom-input';
        customInput.placeholder = 'Optional: focus on something specific (e.g. "highlight CCTV posts")';
        card.appendChild(customInput);

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'report-picker-generate-btn';
        btn.textContent = 'Generate report ▸';
        btn.onclick = () => {
            const isTopic = topicRadio.checked;
            const activeList = isTopic ? topicList : trendingList;
            const components = activeList.checkboxRefs.filter(cb => cb.checked).map(cb => cb.value);
            if (components.length === 0) return;
            btn.disabled = true;
            btn.textContent = 'Building report…';
            [...topicList.checkboxRefs, ...trendingList.checkboxRefs].forEach(cb => cb.disabled = true);
            trendingRadio.disabled = true;
            topicRadio.disabled = true;
            customInput.disabled = true;
            const reportSelection = {
                report_id: data.report_id,
                report_type: isTopic ? 'topic' : 'trending',
                components,
                custom_instructions: customInput.value.trim(),
            };
            if (isTopic) {
                reportSelection.topics = topicInfo.topics;
            } else {
                reportSelection.date_range = trendingInfo.date_range;
            }
            sendMessage({
                overrideText: 'Generate the confirmed report',
                displayText: 'Generate report ▸',
                reportSelection,
            });
        };
        card.appendChild(btn);

        return card;
    }

    // Builds the interactive Ad-hoc AI-Generated Report Preview card sent by
    // ollamaagent2.py's llm_validator_node when an ad-hoc layout is generated.
    // Displays the HTML layout preview in an iframe, provides a "Looks good, Build Report"
    // confirmation button, and an interactive "Edit / Refine Requirements" section.
    function buildAdhocReportPreviewCard(data) {
        const card = document.createElement('div');
        card.className = 'chart-container adhoc-preview-card';

        // Title
        const title = document.createElement('div');
        title.className = 'report-picker-title';
        title.textContent = `📄 AI-Generated Layout Preview — "${data.topic_title || 'Intelligence Report'}"`;
        card.appendChild(title);

        // Meta badges
        const metaRow = document.createElement('div');
        metaRow.className = 'adhoc-meta-row';
        const tplBadge = document.createElement('span');
        tplBadge.className = 'adhoc-badge';
        tplBadge.innerHTML = `Template: <code>${data.template_id}</code>`;
        metaRow.appendChild(tplBadge);

        const statusBadge = document.createElement('span');
        const isReady = (data.layout_status || 'ready') === 'ready';
        statusBadge.className = `adhoc-badge ${isReady ? 'status-ready' : 'status-fallback'}`;
        statusBadge.innerHTML = isReady ? `✓ Layout Verified` : `ℹ Fallback Reskin Mode`;
        metaRow.appendChild(statusBadge);
        card.appendChild(metaRow);

        // Preview container + Toolbar
        const previewContainer = document.createElement('div');
        previewContainer.className = 'adhoc-preview-container';

        const toolbar = document.createElement('div');
        toolbar.className = 'adhoc-preview-toolbar';
        toolbar.innerHTML = `<span><strong>HTML Layout Preview</strong> (Sample placeholder data)</span>`;
        const expandBtn = document.createElement('button');
        expandBtn.type = 'button';
        expandBtn.textContent = '⤢ Expand View';
        let expanded = false;
        expandBtn.onclick = () => {
            expanded = !expanded;
            iframe.classList.toggle('expanded', expanded);
            expandBtn.textContent = expanded ? '⤡ Compact View' : '⤢ Expand View';
        };
        toolbar.appendChild(expandBtn);
        previewContainer.appendChild(toolbar);

        // Iframe preview
        const iframe = document.createElement('iframe');
        iframe.className = 'adhoc-preview-iframe';
        iframe.sandbox = 'allow-same-origin allow-scripts';
        iframe.srcdoc = data.preview_html || '<html><body><p>No preview generated</p></body></html>';
        previewContainer.appendChild(iframe);
        card.appendChild(previewContainer);

        // Actions Row (Confirm & Build PDF)
        const actionsRow = document.createElement('div');
        actionsRow.className = 'adhoc-actions-row';

        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = 'adhoc-confirm-btn';
        confirmBtn.textContent = 'Looks good, Build Report (PDF) ▸';

        confirmBtn.onclick = () => {
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Compiling PDF report with live data…';
            if (editBtn) editBtn.disabled = true;
            if (editTextarea) editTextarea.disabled = true;

            const isTopic = Boolean(data.scope && data.scope.topics && data.scope.topics.length > 0);
            const topicId = isTopic ? data.scope.topics[0].topic_id : null;
            const dateRange = (data.scope && data.scope.date_range) ? data.scope.date_range : null;

            const reportSelection = {
                report_type: 'adhoc',
                template_id: data.template_id,
                topic_id: topicId,
                topic_title: data.topic_title,
                date_range: dateRange,
                scope: data.scope,
                custom_instructions: data.brief ? (data.brief.design_notes || '') : '',
            };

            sendMessage({
                overrideText: 'Build the confirmed custom report',
                displayText: 'Build Report (PDF) ▸',
                reportSelection,
            });
        };
        actionsRow.appendChild(confirmBtn);
        card.appendChild(actionsRow);

        // Edit / Refinement Section (user requested!)
        const editSection = document.createElement('div');
        editSection.className = 'adhoc-edit-section';

        const editHeader = document.createElement('div');
        editHeader.className = 'adhoc-edit-header';
        editHeader.innerHTML = `✏️ <span>Want to edit layout? Enter new requirements:</span>`;
        editSection.appendChild(editHeader);

        const editTextarea = document.createElement('textarea');
        editTextarea.className = 'adhoc-edit-textarea';
        editTextarea.placeholder = 'e.g. Change to dark cyber theme, include top 5 hashtags and a bar chart for platform engagement...';
        editSection.appendChild(editTextarea);

        const editActions = document.createElement('div');
        editActions.className = 'adhoc-edit-actions';

        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'adhoc-edit-btn';
        editBtn.textContent = '🔄 Update / Regenerate Preview';

        editBtn.onclick = () => {
            const userEdit = editTextarea.value.trim();
            if (!userEdit) {
                alert('Please enter your modified requirements or design notes.');
                return;
            }
            editBtn.disabled = true;
            editBtn.textContent = 'Generating updated preview…';
            confirmBtn.disabled = true;
            editTextarea.disabled = true;

            const topicName = data.topic_title || 'this topic';
            const refinedQuery = `Make a custom report for ${topicName}. Additional design notes: ${userEdit}`;

            sendMessage({
                overrideText: refinedQuery,
                displayText: `Update preview: "${userEdit}"`,
            });
        };

        editActions.appendChild(editBtn);
        editSection.appendChild(editActions);
        card.appendChild(editSection);

        return card;
    }

    // Builds the write-action confirmation card sent by
    // check_and_run_endpoint_routes_node (see ollamaagent2.py) when a query
    // resolves to one of the 13 WRITE_ENDPOINT_MARKERS endpoints.
    // `data` = the confirm_payload emitted verbatim by the backend:
    // {type, write_id, endpoint, method, payload}.
    // Same cross-turn pattern as buildReportPickerCard/report_selection:
    // there's no server-side memory of this card between turns, so on
    // "Confirm" we echo `data` straight back as `endpoint_write_confirmation`
    // on the very next request — that payload IS the memory (see
    // endpoint_write_executor_node, which re-validates it server-side rather
    // than trusting it blindly).
    function buildEndpointWriteConfirmationCard(data) {
        const card = document.createElement('div');
        card.className = 'chart-container endpoint-write-card';

        const title = document.createElement('div');
        title.className = 'endpoint-write-title';
        title.innerHTML = `⚠️ <span>This will write data to the Matrix system</span>`;
        card.appendChild(title);

        const actionRow = document.createElement('div');
        actionRow.className = 'endpoint-write-action';
        const methodBadge = document.createElement('span');
        methodBadge.className = 'endpoint-write-method';
        methodBadge.textContent = (data.method || 'POST').toUpperCase();
        actionRow.appendChild(methodBadge);
        const endpointName = document.createElement('code');
        endpointName.className = 'endpoint-write-path';
        endpointName.textContent = data.endpoint;
        actionRow.appendChild(endpointName);
        card.appendChild(actionRow);

        const fields = data.payload || {};
        const fieldKeys = Object.keys(fields);
        if (fieldKeys.length > 0) {
            const fieldList = document.createElement('div');
            fieldList.className = 'endpoint-write-fields';
            fieldKeys.forEach(key => {
                const row = document.createElement('div');
                row.className = 'endpoint-write-field-row';
                const label = document.createElement('span');
                label.className = 'endpoint-write-field-label';
                label.textContent = key;
                const value = document.createElement('span');
                value.className = 'endpoint-write-field-value';
                value.textContent = String(fields[key]);
                row.appendChild(label);
                row.appendChild(value);
                fieldList.appendChild(row);
            });
            card.appendChild(fieldList);
        }

        const btnRow = document.createElement('div');
        btnRow.className = 'endpoint-write-btn-row';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'endpoint-write-cancel-btn';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.onclick = () => {
            confirmBtn.disabled = true;
            cancelBtn.disabled = true;
            cancelBtn.textContent = 'Cancelled';
            sendMessage({
                overrideText: 'No, cancel that action',
                displayText: 'Cancel ✗',
            });
        };
        btnRow.appendChild(cancelBtn);

        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = 'endpoint-write-confirm-btn';
        confirmBtn.textContent = 'Confirm ▸';
        confirmBtn.onclick = () => {
            confirmBtn.disabled = true;
            cancelBtn.disabled = true;
            confirmBtn.textContent = 'Sending…';
            sendMessage({
                overrideText: 'Yes, confirm that action',
                displayText: 'Confirm ✓',
                endpointWriteConfirmation: data,
            });
        };
        btnRow.appendChild(confirmBtn);

        card.appendChild(btnRow);

        return card;
    }

    // Builds the endpoint checkbox picker card sent by
    // check_and_run_endpoint_routes_node (see ollamaagent2.py) when Stage 2
    // finds one or more relevant READ endpoints instead of forcing a single
    // strict pick. `data` = {type, selection_id, query, candidates: [
    //   {endpoint, method, payload, relevance, reasoning}, ... ]}.
    // Same cross-turn pattern as buildReportPickerCard/buildEndpointWrite-
    // ConfirmationCard: there's no server-side memory of this card between
    // turns, so on "Run selected" we echo the chosen candidates straight
    // back as `endpoint_multi_selection` on the very next request — that
    // payload IS the memory (see endpoint_multi_run_executor_node, which
    // re-validates every item server-side and refuses any write endpoint
    // rather than trusting the echo blindly).
    // Renders each candidate as a plain-language action the user can pick —
    // deliberately NEVER shows the raw endpoint URL, HTTP method, or any
    // other technical/API detail. `label` (preferred) is a
    // plain-language sentence written by _rank_endpoint_candidates
    // describing what running this action WOULD DO for the user (e.g.
    // "Get the list of villages under tehsil 105") with no endpoint/URL
    // wording. `reasoning` (why it matches) is used as a fallback only if
    // an older backend hasn't been updated to send `label` yet. The
    // technical endpoint/method/payload still travel in `data.candidates`
    // for execution — they're just never rendered.
    function _endpointCandidateDisplayText(cand) {
        return cand.label || cand.reasoning || 'A data lookup based on your request.';
    }

    function buildEndpointMultiSelectionCard(data) {
        const card = document.createElement('div');
        card.className = 'chart-container endpoint-multi-card';

        const title = document.createElement('div');
        title.className = 'endpoint-multi-title';
        const count = data.candidates.length;
        title.innerHTML = `🔎 <span>Found ${count} thing${count === 1 ? '' : 's'} that could answer this — choose what to run</span>`;
        card.appendChild(title);

        const list = document.createElement('div');
        list.className = 'endpoint-multi-list';
        const checkboxRefs = [];

        data.candidates.forEach((cand, idx) => {
            const row = document.createElement('label');
            row.className = 'endpoint-multi-option';

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = String(idx);
            // Pre-check the higher-relevance matches, leave low-confidence ones unchecked
            cb.checked = (cand.relevance || '').toLowerCase() !== 'low';
            row.appendChild(cb);

            const txt = document.createElement('span');
            txt.className = 'endpoint-multi-option-text';

            const headRow = document.createElement('span');
            headRow.className = 'endpoint-multi-option-head';
            const label = document.createElement('span');
            label.className = 'endpoint-multi-option-label';
            label.textContent = _endpointCandidateDisplayText(cand);
            headRow.appendChild(label);
            if (cand.relevance) {
                const relBadge = document.createElement('span');
                relBadge.className = 'endpoint-multi-option-relevance endpoint-multi-option-relevance-' + cand.relevance.toLowerCase();
                relBadge.textContent = cand.relevance;
                headRow.appendChild(relBadge);
            }
            txt.appendChild(headRow);

            row.appendChild(txt);
            list.appendChild(row);
            checkboxRefs.push(cb);
        });

        card.appendChild(list);

        const btnRow = document.createElement('div');
        btnRow.className = 'endpoint-multi-btn-row';

        const runBtn = document.createElement('button');
        runBtn.type = 'button';
        runBtn.className = 'endpoint-multi-run-btn';
        runBtn.textContent = 'Run selected ▸';
        runBtn.onclick = () => {
            const selected = checkboxRefs
                .filter(cb => cb.checked)
                .map(cb => {
                    const cand = data.candidates[Number(cb.value)];
                    return { endpoint: cand.endpoint, method: cand.method, payload: cand.payload || {} };
                });
            if (selected.length === 0) return;

            checkboxRefs.forEach(cb => cb.disabled = true);
            runBtn.disabled = true;
            runBtn.textContent = 'Running…';

            sendMessage({
                overrideText: `Run ${selected.length} selected endpoint${selected.length === 1 ? '' : 's'}`,
                displayText: `Run selected (${selected.length}) ▸`,
                endpointMultiSelection: selected,
                // The real standalone question, captured from the card payload
                // check_and_run_endpoint_routes_node sent on turn 1 (data.query).
                // Without this, endpoint_multi_run_executor_node on the backend
                // only sees the button label above ("Run 2 selected endpoints"),
                // which is useless for summarizing the results.
                endpointMultiSelectionQuery: data.query,
            });
        };
        btnRow.appendChild(runBtn);
        card.appendChild(btnRow);

        return card;
    }

    function addMessage(content, sender, id = null, isHtml = false) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${sender}`;
        if (id) msgDiv.id = id;

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';

        if (isHtml) {
            contentDiv.innerHTML = content;
        } else {
            contentDiv.textContent = content;
        }

        msgDiv.appendChild(contentDiv);
        messagesDiv.appendChild(msgDiv);

        // Add action buttons for AI messages (e.g. Listen)
        if (sender === 'ai' && id !== 'typingIndicator') {
            addListenButton(msgDiv, contentDiv);
        }

        if (isHtml && sender === 'ai') {
            renderChartsAndGraphs(contentDiv);
        }
    }

    function renderBarChart(container, data) {
        const margin = { top: 20, right: 20, bottom: 60, left: 60 };
        const width = Math.min(container.parentElement.clientWidth - 40, 600) - margin.left - margin.right;
        const height = 300 - margin.top - margin.bottom;

        // Clear any existing content
        container.innerHTML = '';

        const svg = d3.select(container)
            .append("svg")
            .attr("width", width + margin.left + margin.right)
            .attr("height", height + margin.top + margin.bottom)
            .append("g")
            .attr("transform", `translate(${margin.left},${margin.top})`);

        const x = d3.scaleBand()
            .range([0, width])
            .domain(data.map(d => String(d.label).substring(0, 15)))
            .padding(0.2);

        svg.append("g")
            .attr("transform", `translate(0,${height})`)
            .attr("class", "d3-axis")
            .call(d3.axisBottom(x))
            .selectAll("text")
            .attr("transform", "translate(-10,0)rotate(-45)")
            .style("text-anchor", "end");

        const maxVal = d3.max(data, d => +d.value) || 10;
        const y = d3.scaleLinear()
            .domain([0, maxVal])
            .range([height, 0]);

        svg.append("g")
            .attr("class", "d3-axis")
            .call(d3.axisLeft(y));

        svg.selectAll(".d3-bar")
            .data(data)
            .enter()
            .append("rect")
            .attr("class", "d3-bar")
            .attr("x", d => x(String(d.label).substring(0, 15)))
            .attr("width", x.bandwidth())
            .attr("y", d => y(+d.value))
            .attr("height", d => height - y(+d.value));
    }

    // ── Chat URL routing (ChatGPT-style /c/<chatId>) ────────────────────────
    // Loads the right chat based on the current URL: /c/<chatId> restores
    // that conversation, / shows a blank new chat. Runs on initial page load
    // and again on back/forward navigation (popstate) — pushState alone
    // doesn't fire any load event, so without this the URL would change but
    // the visible chat wouldn't follow it.
    function loadChatFromUrl() {
        const match = window.location.pathname.match(/^\/c\/([^/]+)\/?$/);
        if (match) {
            restoreSession(match[1]);
        } else {
            currentChatId = null;
            if (contentWrapper.classList.contains('chat-active')) {
                // Navigated back to "/" (e.g. via Back button) from an active chat
                messagesDiv.innerHTML = '';
                contentWrapper.classList.remove('chat-active');
            }
        }
    }

    window.addEventListener('popstate', loadChatFromUrl);
    loadChatFromUrl();
});