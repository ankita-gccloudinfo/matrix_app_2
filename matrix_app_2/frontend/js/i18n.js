const translations = {
  en: {
    // Navigation
    locationMap: 'Location Map',
    chatHistory: 'Chat History',
    socialMediaFeed: 'Social Media Feed',
    settings: 'Settings',
    newChat: 'New Chat',
    search: 'Search',

    // Buttons & Actions
    uploadPDF: 'Upload PDF',
    askSmartSMI: 'Ask smart SMI...',
    listening: 'Listening... Speak now',
    talkToAvatar: 'Talk to Avatar',
    monitorReport: 'Monitor Report',
    closeModal: 'Close',
    save: 'Save',
    cancel: 'Cancel',

    // Messages
    detectingLocation: 'Detecting your location...',
    connectingAvatar: 'Connecting to avatar...',
    avatarReady: 'Avatar ready. Tap the mic and ask a question.',
    avatarThinking: 'Thinking...',
    avatarSpeaking: 'Speaking...',
    loadingPosts: 'Loading posts...',
    noPosts: 'No posts found for this district.',
    errorLoading: 'Error loading feed.',

    // Settings
    language: 'Language',
    selectLanguage: 'Select Language',
    hindi: 'हिंदी (Hindi)',
    english: 'English',
    theme: 'Theme',
    darkMode: 'Dark Mode',
    lightMode: 'Light Mode',
    settingsTitle: 'Settings',

    // Other
    located: 'Located',
    postsToday: 'Posts Today',
    allTimePostsIn: 'All-time posts in',

    // Greeting stats ({district} and {count} are filled in at runtime)
    greetingToday: 'In {district}, you got {count} posts today.',
    greetingYesterday: 'In {district}, you got {count} posts yesterday.',
    greetingWeek: 'In {district}, you got {count} posts this week.',
    greetingAllTime: 'All-time posts in {district}: {count}',
  },
  hi: {
    // Navigation
    locationMap: 'स्थान मानचित्र',
    chatHistory: 'चैट इतिहास',
    socialMediaFeed: 'सोशल मीडिया फ़ीड',
    settings: 'सेटिंग्स',
    newChat: 'नई चैट',
    search: 'खोज',

    // Buttons & Actions
    uploadPDF: 'PDF अपलोड करें',
    askSmartSMI: 'स्मार्ट SMI से पूछें...',
    listening: 'सुन रहे हैं... अब बोलें',
    talkToAvatar: 'अवतार से बात करें',
    monitorReport: 'निगरानी रिपोर्ट',
    closeModal: 'बंद करें',
    save: 'सहेजें',
    cancel: 'रद्द करें',

    // Messages
    detectingLocation: 'आपकी स्थिति का पता लगा रहे हैं...',
    connectingAvatar: 'अवतार से जुड़ रहे हैं...',
    avatarReady: 'अवतार तैयार है। माइक टैप करें और कोई सवाल पूछें।',
    avatarThinking: 'सोच रहे हैं...',
    avatarSpeaking: 'बोल रहे हैं...',
    loadingPosts: 'पोस्ट लोड हो रही हैं...',
    noPosts: 'इस जिले के लिए कोई पोस्ट नहीं मिली।',
    errorLoading: 'फ़ीड लोड करने में त्रुटि।',

    // Settings
    language: 'भाषा',
    selectLanguage: 'भाषा चुनें',
    hindi: 'हिंदी (Hindi)',
    english: 'English',
    theme: 'थीम',
    darkMode: 'डार्क मोड',
    lightMode: 'लाइट मोड',
    settingsTitle: 'सेटिंग्स',

    // Other
    located: 'स्थित',
    postsToday: 'आज की पोस्ट',
    allTimePostsIn: 'में सभी समय की पोस्ट',

    // Greeting stats ({district} and {count} are filled in at runtime)
    greetingToday: '{district} में, आपको आज {count} पोस्ट मिलीं।',
    greetingYesterday: '{district} में, आपको कल {count} पोस्ट मिलीं।',
    greetingWeek: '{district} में, आपको इस सप्ताह {count} पोस्ट मिलीं।',
    greetingAllTime: '{district} में सभी समय की पोस्ट: {count}',
  }
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
