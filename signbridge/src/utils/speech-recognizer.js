/**
 * SignBridge 语音识别器 v2
 *
 * 策略：
 * 1. 优先使用 Web Speech API (SpeechRecognition) — 不需要额外权限
 * 2. 如果 API 不存在或返回 not-allowed，静默降级到演示模式
 * 3. 永不弹出麦克风权限请求
 */

export class SpeechRecognizer {
  constructor(options = {}) {
    this.onResult = options.onResult || (() => {});
    this.onError = options.onError || (() => {});
    this.onStateChange = options.onStateChange || (() => {});
    this.language = options.language || "zh-CN";
    this.interimResults = options.interimResults !== false;
    this._recognition = null;
    this._isRunning = false;
    this._restartTimeout = null;
    this._silent = false; // 静默降级
  }

  static isSupported() {
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  }

  /**
   * 开始识别 — 不需要额外权限
   */
  async start() {
    if (this._isRunning) return;
    this._isRunning = true;
    this.onStateChange("starting");

    if (!SpeechRecognizer.isSupported()) {
      console.log(
        "[SignBridge] SpeechRecognition not supported, entering demo mode",
      );
      this._silent = true;
      this.onStateChange("demo");
      return;
    }

    try {
      this._startNative();
    } catch (e) {
      console.warn("[SignBridge] SpeechRecognition failed:", e.message);
      this._silent = true;
      this.onStateChange("demo");
    }
  }

  _startNative() {
    const API = window.SpeechRecognition || window.webkitSpeechRecognition;
    this._recognition = new API();
    this._recognition.continuous = true;
    this._recognition.interimResults = this.interimResults;
    this._recognition.lang = this.language;
    this._recognition.maxAlternatives = 1;

    this._recognition.onresult = (event) => {
      let final = "";
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) final += event.results[i][0].transcript;
        else interim += event.results[i][0].transcript;
      }
      if (final) {
        this.onResult({
          text: final,
          isFinal: true,
          confidence: 0.8,
          timestamp: Date.now(),
        });
      }
      if (interim) {
        this.onResult({
          text: interim,
          isFinal: false,
          confidence: 0.5,
          timestamp: Date.now(),
        });
      }
    };

    this._recognition.onerror = (event) => {
      // not-allowed = 无法获取麦克风权限 — 静默降级，不报错
      if (
        event.error === "not-allowed" ||
        event.error === "service-not-allowed"
      ) {
        console.log("[SignBridge] Speech not allowed, switching to demo mode");
        this._silent = true;
        this._isRunning = false;
        this.onStateChange("demo");
        this.onError(new Error("not-allowed"));
        return;
      }
      // 其他错误静默处理
      if (event.error !== "no-speech" && event.error !== "aborted") {
        console.warn("[SignBridge] Speech recognition warning:", event.error);
      }
    };

    this._recognition.onend = () => {
      // 不自动重启—让调用方决定
    };

    this._recognition.start();
    this.onStateChange("running");
  }

  /**
   * 是否已静默降级到演示模式
   */
  get isSilent() {
    return this._silent;
  }

  stop() {
    this._isRunning = false;
    this._silent = false;
    clearTimeout(this._restartTimeout);
    if (this._recognition) {
      try {
        this._recognition.stop();
      } catch (e) {}
      this._recognition = null;
    }
    this.onStateChange("stopped");
  }

  setLanguage(lang) {
    this.language = lang;
    if (this._recognition) this._recognition.lang = lang;
  }

  destroy() {
    this.stop();
    this.onResult = () => {};
    this.onError = () => {};
    this.onStateChange = () => {};
  }
}
