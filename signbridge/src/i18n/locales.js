/**
 * SignBridge 国际化支持
 * Supports: zh-CN, zh-TW, en, ja, ko
 */
const LOCALES = {
  "zh-CN": {
    name: "中文（简体）",
    title: "SignBridge — 手语翻译",
    description: "实时将视频语音翻译成手语，通过3D虚拟人展示",
    settings: "设置",
    avatar: "虚拟人",
    language: "语言",
    sourceLanguage: "视频语言",
    targetSignLanguage: "手语类型",
    avatarStyle: "虚拟人外观",
    avatarSize: "虚拟人大小",
    avatarPosition: "虚拟人位置",
    positionBottomRight: "右下角",
    positionBottomLeft: "左下角",
    positionTopRight: "右上角",
    positionTopLeft: "左上角",
    enableAutoDetect: "自动检测视频",
    enableSubtitles: "显示字幕",
    voiceVolume: "语音音量",
    speed: "手语速度",
    about: "关于",
    start: "开始翻译",
    stop: "停止翻译",
    loading: "加载中...",
    noVideo: "未检测到视频",
    error: "出错了",
    errorNoSpeech: "无法访问麦克风",
    errorNoVideo: "页面上没有找到视频",
    footer: "SignBridge — 让信息无障碍",
    signLanguageTypes: {
      csl: "中国手语 (CSL)",
      asl: "美国手语 (ASL)",
      bsl: "英国手语 (BSL)",
      jsl: "日本手语 (JSL)",
      ksl: "韩国手语 (KSL)",
      tsl: "台湾手语 (TSL)",
    },
    avatarStyles: {
      default: "默认",
      friendly: "友好",
      professional: "专业",
      anime: "动漫风格",
    },
    voiceVolumeLevels: {
      low: "低（仅视频）",
      medium: "中（视频+手语）",
      high: "高（仅手语）",
    },
  },
  en: {
    name: "English",
    title: "SignBridge — Sign Language Translation",
    description:
      "Real-time video speech to sign language translation via 3D avatar",
    settings: "Settings",
    avatar: "Avatar",
    language: "Language",
    sourceLanguage: "Video Language",
    targetSignLanguage: "Sign Language",
    avatarStyle: "Avatar Style",
    avatarSize: "Avatar Size",
    avatarPosition: "Avatar Position",
    positionBottomRight: "Bottom Right",
    positionBottomLeft: "Bottom Left",
    positionTopRight: "Top Right",
    positionTopLeft: "Top Left",
    enableAutoDetect: "Auto-detect Video",
    enableSubtitles: "Show Subtitles",
    voiceVolume: "Voice Volume",
    speed: "Sign Speed",
    about: "About",
    start: "Start Translation",
    stop: "Stop Translation",
    loading: "Loading...",
    noVideo: "No video detected",
    error: "Error",
    errorNoSpeech: "Cannot access microphone",
    errorNoVideo: "No video found on this page",
    footer: "SignBridge — Making Information Accessible",
    signLanguageTypes: {
      csl: "Chinese Sign Language (CSL)",
      asl: "American Sign Language (ASL)",
      bsl: "British Sign Language (BSL)",
      jsl: "Japanese Sign Language (JSL)",
      ksl: "Korean Sign Language (KSL)",
      tsl: "Taiwan Sign Language (TSL)",
    },
    avatarStyles: {
      default: "Default",
      friendly: "Friendly",
      professional: "Professional",
      anime: "Anime Style",
    },
    voiceVolumeLevels: {
      low: "Low (video only)",
      medium: "Medium (video + sign)",
      high: "High (sign only)",
    },
  },
  ja: {
    name: "日本語",
    title: "SignBridge — 手話翻訳",
    description: "動画の音声をリアルタイムで手話に翻訳、3Dアバターで表示",
    settings: "設定",
    avatar: "アバター",
    language: "言語",
    sourceLanguage: "動画の言語",
    targetSignLanguage: "手話の種類",
    avatarStyle: "アバタースタイル",
    avatarSize: "アバターサイズ",
    avatarPosition: "アバター位置",
    positionBottomRight: "右下",
    positionBottomLeft: "左下",
    positionTopRight: "右上",
    positionTopLeft: "左上",
    enableAutoDetect: "動画を自動検出",
    enableSubtitles: "字幕を表示",
    voiceVolume: "音声音量",
    speed: "手話の速度",
    about: "について",
    start: "翻訳開始",
    stop: "翻訳停止",
    loading: "読み込み中...",
    noVideo: "動画が見つかりません",
    error: "エラー",
    errorNoSpeech: "マイクにアクセスできません",
    errorNoVideo: "ページに動画が見つかりません",
    footer: "SignBridge — 情報をアクセシブルに",
    signLanguageTypes: {
      csl: "中国手話 (CSL)",
      asl: "アメリカ手話 (ASL)",
      bsl: "イギリス手話 (BSL)",
      jsl: "日本手話 (JSL)",
      ksl: "韓国手話 (KSL)",
    },
    avatarStyles: {
      default: "デフォルト",
      friendly: "フレンドリー",
      professional: "プロフェッショナル",
      anime: "アニメ風",
    },
  },
};

const FALLBACK_LOCALE = "en";

let _currentLocale = null;

export function getLocale() {
  return _currentLocale || navigator.language || FALLBACK_LOCALE;
}

export function setLocale(locale) {
  _currentLocale = locale;
}

export function t(key, replacements = {}) {
  const locale = getLocale();
  // Try exact match, then language-only (e.g., 'zh' from 'zh-CN')
  let dict =
    LOCALES[locale] ||
    LOCALES[locale.split("-")[0]] ||
    LOCALES[FALLBACK_LOCALE];

  const keys = key.split(".");
  let value = dict;
  for (const k of keys) {
    if (value && typeof value === "object") value = value[k];
    else {
      value = undefined;
      break;
    }
  }

  if (value === undefined) {
    // Fallback chain
    dict = LOCALES[FALLBACK_LOCALE];
    value = dict;
    for (const k of keys) {
      if (value && typeof value === "object") value = value[k];
      else break;
    }
  }

  if (typeof value !== "string") return key;

  // Simple replacements
  return value.replace(/\{(\w+)\}/g, (_, k) => replacements[k] ?? `{${k}}`);
}

export function getSupportedLocales() {
  return Object.entries(LOCALES).map(([code, data]) => ({
    code,
    name: data.name,
  }));
}

export { LOCALES };
