/**
 * SignBridge 国际化支持
 * Supports: zh-CN, en, ja
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
    errorNoVideo: "页面上没有找到视频",
    ready: "已就绪",
    translating: "正在翻译...",
    unavailable: "当前页面不可用",
    inputPlaceholder: "输入文字，虚拟人打手语...",
    send: "发送",
    sent: "已发送",
    audioOff: "视频声音：关闭",
    audioOn: "视频声音：开启",
    audioStopped: "已关闭",
    audioListening: "识别中...",
    audioStarting: "正在捕获声音...",
    audioUnavailable: "当前页面不可捕获",
    audioCaptureFailed: "声音捕获失败",
    audioCloudKeyRequired: "请先配置云端 API Key",
    audioPermissionRequired: "请先保存识别设置并授权服务地址",
    audioLocalUnavailable: "请先一键部署本地 Whisper",
    asrSettings: "声音识别设置",
    asrTitle: "视频声音识别",
    asrPurpose: "选择本地 Whisper 或云端 ASR，将当前视频声音转换为手语动作。",
    asrProvider: "识别方式",
    asrLocal: "本地 Whisper",
    asrCloud: "云端 ASR",
    asrLocalSettings: "本地 Whisper 设置",
    asrLocalPrivacy:
      "模型和音频都在浏览器扩展内处理，视频声音不会上传到识别服务。",
    asrDeployLocal: "一键部署本地 Whisper",
    asrEndpoint: "服务地址",
    asrModel: "模型",
    asrModelTiny: "tiny（最快，约 75 MB）",
    asrModelBase: "base（均衡，约 150 MB）",
    asrModelSmall: "small（更准确，约 500 MB）",
    asrDeployHint: "点击后自动下载并缓存模型，无需安装 Python 或运行本地服务。",
    asrDeployRequired: "当前模型尚未部署。",
    asrRequestingModelPermission: "正在申请模型下载权限...",
    asrDeploying: "正在下载并初始化模型：{progress}%",
    asrDeployReady: "本地模型 {model} 已就绪。",
    asrDeployFailed: "本地模型部署失败",
    asrCloudSettings: "云端 ASR 设置",
    asrCloudPrivacy:
      "视频音频分片会发送到你配置的服务，请确认服务的隐私与计费规则。",
    asrApiKey: "API Key",
    asrCommonSettings: "通用设置",
    asrLanguage: "识别语言",
    asrChunkSeconds: "音频分片",
    asrTest: "测试连接",
    asrSave: "保存设置",
    asrPermissionDenied: "未授予该服务地址的网络权限。",
    asrSaved: "设置已保存。",
    asrInvalidConfig: "设置无效，请检查服务地址和模型。",
    asrTesting: "正在测试识别服务...",
    asrTestPassed: "连接测试通过。",
    asrTestFailed: "连接测试失败",
    poseEditor: "姿势编辑器",
    recorder: "录制工具",
    help: "帮助文档",
    tagline: "让信息无障碍",
    auto: "自动检测",
    simplifiedChinese: "中文（普通话）",
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
    errorNoVideo: "No video found on this page",
    ready: "Ready",
    translating: "Translating...",
    unavailable: "Unavailable on this page",
    inputPlaceholder: "Enter text for the avatar to sign...",
    send: "Send",
    sent: "Sent",
    audioOff: "Video audio: Off",
    audioOn: "Video audio: On",
    audioStopped: "Stopped",
    audioListening: "Recognizing...",
    audioStarting: "Capturing audio...",
    audioUnavailable: "Audio capture is unavailable on this page",
    audioCaptureFailed: "Audio capture failed",
    audioCloudKeyRequired: "Configure the cloud API key first",
    audioPermissionRequired: "Save ASR settings and allow the service origin",
    audioLocalUnavailable: "Deploy local Whisper first",
    asrSettings: "Audio recognition settings",
    asrTitle: "Video audio recognition",
    asrPurpose:
      "Choose local Whisper or cloud ASR to convert video audio into sign language motion.",
    asrProvider: "Recognition provider",
    asrLocal: "Local Whisper",
    asrCloud: "Cloud ASR",
    asrLocalSettings: "Local Whisper settings",
    asrLocalPrivacy:
      "The model and audio stay inside the extension. Video audio is not uploaded to an ASR service.",
    asrDeployLocal: "Deploy local Whisper",
    asrEndpoint: "Service endpoint",
    asrModel: "Model",
    asrModelTiny: "tiny (fastest, about 75 MB)",
    asrModelBase: "base (balanced, about 150 MB)",
    asrModelSmall: "small (more accurate, about 500 MB)",
    asrDeployHint:
      "Downloads and caches the model automatically. Python and a local service are not required.",
    asrDeployRequired: "The selected model is not deployed.",
    asrRequestingModelPermission: "Requesting model download access...",
    asrDeploying: "Downloading and initializing model: {progress}%",
    asrDeployReady: "Local model {model} is ready.",
    asrDeployFailed: "Local model deployment failed",
    asrCloudSettings: "Cloud ASR settings",
    asrCloudPrivacy:
      "Video audio chunks are sent to the configured service. Review its privacy and billing terms.",
    asrApiKey: "API Key",
    asrCommonSettings: "Common settings",
    asrLanguage: "Recognition language",
    asrChunkSeconds: "Audio chunk",
    asrTest: "Test connection",
    asrSave: "Save settings",
    asrPermissionDenied: "Network access to this service was not granted.",
    asrSaved: "Settings saved.",
    asrInvalidConfig: "Invalid settings. Check the endpoint and model.",
    asrTesting: "Testing the recognition service...",
    asrTestPassed: "Connection test passed.",
    asrTestFailed: "Connection test failed",
    poseEditor: "Pose editor",
    recorder: "Recorder",
    help: "Help",
    tagline: "Accessible information",
    auto: "Auto detect",
    simplifiedChinese: "Chinese (Mandarin)",
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
    errorNoVideo: "ページに動画が見つかりません",
    ready: "準備完了",
    translating: "翻訳中...",
    unavailable: "このページでは利用できません",
    inputPlaceholder: "手話にするテキストを入力...",
    send: "送信",
    sent: "送信済み",
    audioOff: "動画音声：オフ",
    audioOn: "動画音声：オン",
    audioStopped: "停止中",
    audioListening: "認識中...",
    audioStarting: "音声を取得中...",
    audioUnavailable: "このページでは音声を取得できません",
    audioCaptureFailed: "音声の取得に失敗しました",
    audioCloudKeyRequired: "クラウド API Key を設定してください",
    audioPermissionRequired: "ASR 設定を保存して接続先を許可してください",
    audioLocalUnavailable: "先にローカル Whisper を導入してください",
    asrSettings: "音声認識設定",
    asrTitle: "動画音声認識",
    asrPurpose:
      "ローカル Whisper またはクラウド ASR で動画音声を手話動作に変換します。",
    asrProvider: "認識方式",
    asrLocal: "ローカル Whisper",
    asrCloud: "クラウド ASR",
    asrLocalSettings: "ローカル Whisper 設定",
    asrLocalPrivacy:
      "モデルと音声は拡張機能内で処理され、動画音声は認識サービスへ送信されません。",
    asrDeployLocal: "ローカル Whisper を導入",
    asrEndpoint: "サービス URL",
    asrModel: "モデル",
    asrModelTiny: "tiny（最速、約 75 MB）",
    asrModelBase: "base（バランス、約 150 MB）",
    asrModelSmall: "small（高精度、約 500 MB）",
    asrDeployHint:
      "クリックするとモデルを自動でダウンロードして保存します。Python やローカルサービスは不要です。",
    asrDeployRequired: "選択したモデルはまだ導入されていません。",
    asrRequestingModelPermission: "モデルのダウンロード権限を確認中...",
    asrDeploying: "モデルをダウンロードして初期化中：{progress}%",
    asrDeployReady: "ローカルモデル {model} の準備が完了しました。",
    asrDeployFailed: "ローカルモデルの導入に失敗しました",
    asrCloudSettings: "クラウド ASR 設定",
    asrCloudPrivacy:
      "動画音声は設定したサービスへ送信されます。プライバシーと料金を確認してください。",
    asrApiKey: "API Key",
    asrCommonSettings: "共通設定",
    asrLanguage: "認識言語",
    asrChunkSeconds: "音声チャンク",
    asrTest: "接続テスト",
    asrSave: "設定を保存",
    asrPermissionDenied: "このサービスへのネットワーク権限がありません。",
    asrSaved: "設定を保存しました。",
    asrInvalidConfig: "設定が無効です。URL とモデルを確認してください。",
    asrTesting: "認識サービスをテストしています...",
    asrTestPassed: "接続テストに成功しました。",
    asrTestFailed: "接続テストに失敗しました",
    poseEditor: "ポーズ編集",
    recorder: "録画ツール",
    help: "ヘルプ",
    tagline: "情報をアクセシブルに",
    auto: "自動検出",
    simplifiedChinese: "中国語（標準語）",
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
