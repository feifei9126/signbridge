/**
 * SignBridge Popup v2
 * 新增: 手动输入框 - 直接打字驱动虚拟人手语
 */
import { getConfig, setConfig } from "../utils/config.js";
import { setLocale } from "../i18n/locales.js";

class SignBridgePopup {
  constructor() {
    this.config = {};
    this._currentTabId = null;
    this._isActive = false;
    this._micEnabled = false;
  }

  async init() {
    this.config = await getConfig();
    this._currentTabId = (await this._getCurrentTab())?.id;
    if (this.config.uiLocale && this.config.uiLocale !== "auto") {
      setLocale(this.config.uiLocale);
    }
    this._cacheElements();
    this._bindEvents();
    this._populateSettings();
    this._updateUI();
    this._queryStatus();
  }

  _cacheElements() {
    this.elements = {
      toggleBtn: document.getElementById("btnToggle"),
      toggleIcon: document.getElementById("btnToggleIcon"),
      toggleText: document.getElementById("btnToggleText"),
      statusDot: document.getElementById("statusDot"),
      statusText: document.getElementById("statusText"),
      signLanguage: document.getElementById("signLanguage"),
      avatarStyle: document.getElementById("avatarStyle"),
      avatarPosition: document.getElementById("avatarPosition"),
      avatarSize: document.getElementById("avatarSize"),
      sizeValue: document.getElementById("sizeValue"),
      sourceLanguage: document.getElementById("sourceLanguage"),
      showSubtitles: document.getElementById("showSubtitles"),
      autoDetect: document.getElementById("autoDetect"),
      uiLocale: document.getElementById("uiLocale"),
      settingsBtn: document.getElementById("btnSettings"),
      btnPoseEditor: document.getElementById("btnPoseEditor"),
      btnRecordMode: document.getElementById("btnRecordMode"),
      // 新增: 手动输入
      textInput: document.getElementById("textInput"),
      btnSendText: document.getElementById("btnSendText"),
      btnHelp: document.getElementById("btnHelp"),
      btnMic: document.getElementById("btnMic"),
      micStatus: document.getElementById("micStatus"),
    };
  }

  _bindEvents() {
    this.elements.toggleBtn?.addEventListener("click", () =>
      this._handleToggle(),
    );
    this.elements.signLanguage?.addEventListener("change", () =>
      this._saveSettings(),
    );
    this.elements.avatarPosition?.addEventListener("change", () =>
      this._saveSettings(),
    );
    this.elements.avatarSize?.addEventListener("input", () => {
      this.elements.sizeValue.textContent =
        this.elements.avatarSize.value + "px";
      this._saveSettings();
    });
    this.elements.sourceLanguage?.addEventListener("change", () =>
      this._saveSettings(),
    );
    this.elements.uiLocale?.addEventListener("change", () =>
      this._saveSettings(),
    );
    this.elements.settingsBtn?.addEventListener("click", () => {
      const settings = document.getElementById("mainSettings");
      if (settings)
        settings.style.display =
          settings.style.display === "none" ? "flex" : "none";
    });
    // 手动发送文字
    this.elements.btnSendText?.addEventListener("click", () =>
      this._sendText(),
    );
    this.elements.textInput?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") this._sendText();
    });

    this.elements.btnPoseEditor?.addEventListener("click", () => {
      const url = chrome.runtime.getURL("avatar/pose-editor.html");
      chrome.tabs.create({ url });
    });
    this.elements.btnRecordMode?.addEventListener("click", () => {
      const url = chrome.runtime.getURL("avatar/record-mode.html");
      chrome.tabs.create({ url });
    });
    this.elements.btnMic?.addEventListener("click", () => this._handleMic());
    this.elements.btnHelp?.addEventListener("click", () => {
      const url = chrome.runtime.getURL("avatar/help.html");
      chrome.tabs.create({ url });
    });
  }

  _populateSettings() {
    if (this.elements.signLanguage)
      this.elements.signLanguage.value =
        this.config.targetSignLanguage || "csl";
    if (this.elements.avatarPosition)
      this.elements.avatarPosition.value =
        this.config.avatarPosition || "bottom-right";
    if (this.elements.avatarSize) {
      this.elements.avatarSize.value = this.config.avatarSize || 180;
      if (this.elements.sizeValue)
        this.elements.sizeValue.textContent =
          (this.config.avatarSize || 180) + "px";
    }
    if (this.elements.sourceLanguage)
      this.elements.sourceLanguage.value = this.config.sourceLanguage || "auto";
    if (this.elements.uiLocale)
      this.elements.uiLocale.value = this.config.uiLocale || "auto";
  }

  _updateUI() {
    if (this._isActive) {
      this.elements.toggleBtn?.classList.add("active");
      if (this.elements.toggleIcon) this.elements.toggleIcon.textContent = "⏹";
      if (this.elements.toggleText)
        this.elements.toggleText.textContent = "停止翻译";
      if (this.elements.statusDot)
        this.elements.statusDot.className = "sb-dot translating";
      if (this.elements.statusText)
        this.elements.statusText.textContent = "正在翻译...";
    } else {
      this.elements.toggleBtn?.classList.remove("active");
      if (this.elements.toggleIcon) this.elements.toggleIcon.textContent = "▶";
      if (this.elements.toggleText)
        this.elements.toggleText.textContent = "开始翻译";
      if (this.elements.statusDot) this.elements.statusDot.className = "sb-dot";
      if (this.elements.statusText)
        this.elements.statusText.textContent = "已就绪";
    }
  }

  async _handleToggle() {
    if (this._isActive) {
      await this._sendMessage("stop");
      this._isActive = false;
    } else {
      await this._sendMessage("start");
      this._isActive = true;
    }
    this._updateUI();
  }

  async _handleMic() {
    var e = this.elements.btnMic;
    if (!e) return;
    if (this._micEnabled) {
      await this._sendMessage("micOff");
      this._micEnabled = !1;
      e.textContent = "🎤 麦克风：关闭";
      e.style.background = "#2a2a4a";
      if (this.elements.micStatus)
        this.elements.micStatus.textContent = "已关闭";
    } else {
      await this._sendMessage("micOn");
      this._micEnabled = !0;
      e.textContent = "🎤 麦克风：开启";
      e.style.background = "#2d6a2d";
      if (this.elements.micStatus)
        this.elements.micStatus.textContent = "监听中...";
    }
  }
  async _sendText() {
    const text = this.elements.textInput?.value?.trim();
    if (!text) return;
    // 发送到 content script
    await this._sendMessage("sendText", { text });
    this.elements.textInput.value = "";
    // 反馈
    const btn = this.elements.btnSendText;
    if (btn) {
      btn.textContent = "✓";
      setTimeout(() => {
        if (btn) btn.textContent = "发送";
      }, 500);
    }
  }

  async _saveSettings() {
    const updates = {
      targetSignLanguage: this.elements.signLanguage?.value,
      avatarPosition: this.elements.avatarPosition?.value,
      avatarSize: parseInt(this.elements.avatarSize?.value),
      sourceLanguage: this.elements.sourceLanguage?.value,
      uiLocale: this.elements.uiLocale?.value,
    };
    this.config = await setConfig(updates);
    if (updates.uiLocale && updates.uiLocale !== "auto")
      setLocale(updates.uiLocale);
    await this._sendMessage("updateConfig", { config: updates });
  }

  async _queryStatus() {
    const response = await this._sendMessage("getStatus");
    if (response) {
      this._isActive = response.active || false;
      this._updateUI();
    }
  }

  async _sendMessage(action, data = {}) {
    try {
      if (this._currentTabId) {
        return await chrome.tabs.sendMessage(this._currentTabId, {
          action,
          ...data,
        });
      }
    } catch (e) {}
    return null;
  }

  async _getCurrentTab() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    return tabs[0] || null;
  }
}

const popup = new SignBridgePopup();
popup.init().catch(console.error);
