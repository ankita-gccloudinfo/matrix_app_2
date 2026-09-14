const translations = {
  en: {
    // Navigation
    chatHistory: 'Chat History',
    settings: 'Settings',
    newChat: 'New Chat',
    search: 'Search',

    // Buttons & Actions
    uploadPDF: 'Upload PDF',
    askSmartSMI: 'Ask smart SMI...',
    listening: 'Listening... Speak now',
    talkToAvatar: 'Talk to Avatar',
    closeModal: 'Close',
    save: 'Save',
    cancel: 'Cancel',

    // Messages
    connectingAvatar: 'Connecting to avatar...',
    avatarReady: 'Avatar ready. Tap the mic and ask a question.',
    avatarThinking: 'Thinking...',
    avatarSpeaking: 'Speaking...',

    // Settings
    language: 'Language',
    selectLanguage: 'Select Language',
    hindi: 'हिंदी (Hindi)',
    english: 'English',
    hinglish: 'Hinglish',
    theme: 'Theme',
    darkMode: 'Dark Mode',
    lightMode: 'Light Mode',
    settingsTitle: 'Settings',
  },
  hi: {
    // Navigation
    chatHistory: 'चैट इतिहास',
    settings: 'सेटिंग्स',
    newChat: 'नई चैट',
    search: 'खोज',

    // Buttons & Actions
    uploadPDF: 'PDF अपलोड करें',
    askSmartSMI: 'स्मार्ट SMI से पूछें...',
    listening: 'सुन रहे हैं... अब बोलें',
    talkToAvatar: 'अवतार से बात करें',
    closeModal: 'बंद करें',
    save: 'सहेजें',
    cancel: 'रद्द करें',

    // Messages
    connectingAvatar: 'अवतार से जुड़ रहे हैं...',
    avatarReady: 'अवतार तैयार है। माइक टैप करें और कोई सवाल पूछें।',
    avatarThinking: 'सोच रहे हैं...',
    avatarSpeaking: 'बोल रहे हैं...',

    // Settings
    language: 'भाषा',
    selectLanguage: 'भाषा चुनें',
    hindi: 'हिंदी (Hindi)',
    english: 'English',
    hinglish: 'Hinglish',
    theme: 'थीम',
    darkMode: 'डार्क मोड',
    lightMode: 'लाइट मोड',
    settingsTitle: 'सेटिंग्स',
  },
  // Minimal — just enough for setLanguage('hinglish')'s `if (translations[lang])`
  // guard to pass. UI chrome intentionally falls back to English via t()'s
  // existing fallback; only the AI's actual answers change for Hinglish.
  hinglish: {
    hinglish: 'Hinglish',
  },
};

class I18n {
  constructor() {
    this.currentLanguage = localStorage.getItem('language') || 'en';
    this.updateHTMLLang();
  }

  t(key, params) {
    let str = translations[this.currentLanguage]?.[key] || translations['en'][key] || key;
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
      }
    }
    return str;
  }

  setLanguage(lang) {
    if (translations[lang]) {
      this.currentLanguage = lang;
      localStorage.setItem('language', lang);
      this.updateHTMLLang();
      return true;
    }
    return false;
  }

  getLanguage() {
    return this.currentLanguage;
  }

  updateHTMLLang() {
    document.documentElement.lang = this.currentLanguage;
    document.documentElement.dir = this.currentLanguage === 'hi' ? 'ltr' : 'ltr';
  }

  // Utility to update all translatable elements
  updatePageTranslations() {
    const translatableElements = document.querySelectorAll('[data-i18n]');
    translatableElements.forEach(el => {
      const key = el.getAttribute('data-i18n');
      el.textContent = this.t(key);
    });

    // Update placeholders
    const placeholderElements = document.querySelectorAll('[data-i18n-placeholder]');
    placeholderElements.forEach(el => {
      const key = el.getAttribute('data-i18n-placeholder');
      el.placeholder = this.t(key);
    });

    // Update titles
    const titleElements = document.querySelectorAll('[data-i18n-title]');
    titleElements.forEach(el => {
      const key = el.getAttribute('data-i18n-title');
      el.title = this.t(key);
    });
  }
}

// Create global i18n instance
window.i18n = new I18n();
