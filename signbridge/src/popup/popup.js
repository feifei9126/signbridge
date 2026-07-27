import { getConfig, setConfig } from "../utils/config.js";
import { setLocale, t } from "../i18n/locales.js";

class SignBridgePopup {
  constructor() {
    this.config = {};
    this.elements = {};
    this._currentTabId = null;
    this._isActive = false;
    this._audioEnabled = false;
    this._settingsTimer = null;
  }

  async init() {
    this.config = await getConfig();
    this._currentTabId = (await this._getCurrentTab())?.id ?? null;
    this._setConfiguredLocale();
    this._cacheElements();
    this._applyTranslations();
    this._bindEvents();
    this._populateSettings();
    this._updateUI();
    await this._queryStatus();
  }

  _cacheElements() {
    this.elements = {
      toggleBtn: document.getElementById("btnToggle"),
      toggleIcon: document.getElementById("btnToggleIcon"),
      toggleText: document.getElementById("btnToggleText"),
      statusDot: document.getElementById("statusDot"),
      statusText: document.getElementById("statusText"),
      signLanguage: document.getElementById("signLanguage"),
      avatarSize: document.getElementById("avatarSize"),
      sizeValue: document.getElementById("sizeValue"),
      sourceLanguage: document.getElementById("sourceLanguage"),
      uiLocale: document.getElementById("uiLocale"),
      settingsBtn: document.getElementById("btnSettings"),
      btnPoseEditor: document.getElementById("btnPoseEditor"),
      btnRecordMode: document.getElementById("btnRecordMode"),
      textInput: document.getElementById("textInput"),
      btnSendText: document.getElementById("btnSendText"),
      btnHelp: document.getElementById("btnHelp"),
      btnAudio: document.getElementById("btnAudio"),
      audioStatus: document.getElementById("audioStatus"),
      btnAsrSettings: document.getElementById("btnAsrSettings"),
    };
  }

  _applyTranslations() {
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      element.textContent = t(element.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
      element.placeholder = t(element.dataset.i18nPlaceholder);
    });
    document.querySelectorAll("[data-i18n-title]").forEach((element) => {
      element.title = t(element.dataset.i18nTitle);
    });
  }

  _bindEvents() {
    this.elements.toggleBtn?.addEventListener("click", () =>
      this._handleToggle(),
    );
    this.elements.signLanguage?.addEventListener("change", () =>
      this._saveSettings(),
    );
    this.elements.avatarSize?.addEventListener("input", () => {
      this._updateSizeLabel();
      this._scheduleSettingsSave();
    });
    this.elements.avatarSize?.addEventListener("change", () =>
      this._saveSettings(),
    );
    this.elements.sourceLanguage?.addEventListener("change", () =>
      this._saveSettings(),
    );
    this.elements.uiLocale?.addEventListener("change", async () => {
      await this._saveSettings();
      this._setConfiguredLocale();
      this._applyTranslations();
      this._updateUI();
      this._updateAudioUI();
    });
    this.elements.settingsBtn?.addEventListener("click", () => {
      const settings = document.getElementById("mainSettings");
      if (settings) settings.hidden = !settings.hidden;
    });
    this.elements.btnSendText?.addEventListener("click", () =>
      this._sendText(),
    );
    this.elements.textInput?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") this._sendText();
    });
    this.elements.btnPoseEditor?.addEventListener("click", () => {
      chrome.tabs.create({
        url: chrome.runtime.getURL("avatar/pose-editor.html"),
      });
    });
    this.elements.btnRecordMode?.addEventListener("click", () => {
      chrome.tabs.create({
        url: chrome.runtime.getURL("avatar/record-mode.html"),
      });
    });
    this.elements.btnAudio?.addEventListener("click", () =>
      this._handleAudio(),
    );
    this.elements.btnAsrSettings?.addEventListener("click", () => {
      chrome.runtime.openOptionsPage();
    });
    this.elements.btnHelp?.addEventListener("click", () => {
      chrome.tabs.create({ url: chrome.runtime.getURL("avatar/help.html") });
    });
  }

  _populateSettings() {
    if (this.elements.signLanguage) {
      const requested = this.config.targetSignLanguage || "csl";
      const supported = Array.from(this.elements.signLanguage.options).some(
        (option) => option.value === requested,
      );
      this.elements.signLanguage.value = supported ? requested : "csl";
    }
    if (this.elements.avatarSize) {
      this.elements.avatarSize.value = this.config.avatarSize || 260;
      this._updateSizeLabel();
    }
    if (this.elements.sourceLanguage) {
      this.elements.sourceLanguage.value = this.config.sourceLanguage || "auto";
    }
    if (this.elements.uiLocale) {
      this.elements.uiLocale.value = this.config.uiLocale || "auto";
    }
  }

  _updateSizeLabel() {
    if (this.elements.sizeValue && this.elements.avatarSize) {
      this.elements.sizeValue.textContent = `${this.elements.avatarSize.value}px`;
    }
  }

  _updateUI() {
    this.elements.toggleBtn?.classList.toggle("active", this._isActive);
    if (this.elements.toggleIcon) {
      this.elements.toggleIcon.textContent = this._isActive ? "■" : "▶";
    }
    if (this.elements.toggleText) {
      this.elements.toggleText.textContent = t(
        this._isActive ? "stop" : "start",
      );
    }
    this._setStatus(this._isActive ? "translating" : "ready", this._isActive);
  }

  _setStatus(key, translating = false) {
    if (this.elements.statusDot) {
      this.elements.statusDot.className = translating
        ? "sb-dot translating"
        : key === "unavailable"
          ? "sb-dot error"
          : "sb-dot";
    }
    if (this.elements.statusText) this.elements.statusText.textContent = t(key);
  }

  async _handleToggle() {
    const requestedActive = !this._isActive;
    const response = await this._sendMessage(
      requestedActive ? "start" : "stop",
    );
    if (!response?.ok) {
      this._setStatus("unavailable");
      return;
    }
    this._isActive = response.active ?? requestedActive;
    this.config = await setConfig({ enabled: this._isActive });
    this._updateUI();
  }

  async _handleAudio() {
    const requestedEnabled = !this._audioEnabled;
    if (requestedEnabled) {
      if (!this._currentTabId) {
        this._setAudioStatus("audioUnavailable");
        return;
      }
      this._setAudioStatus("audioStarting");
      try {
        const response = await this._sendRuntimeMessage({
          type: "ASR_START",
          tabId: this._currentTabId,
        });
        if (!response?.ok) {
          this._setAudioStatus(this._audioErrorKey(response?.error));
          return;
        }
        this._audioEnabled = true;
        this._updateAudioUI();
      } catch (error) {
        console.error("[SignBridge] Tab audio capture failed:", error);
        this._setAudioStatus("audioCaptureFailed");
      }
      return;
    }

    const response = await this._sendRuntimeMessage({ type: "ASR_STOP" });
    if (!response?.ok) {
      this._setAudioStatus("audioUnavailable");
      return;
    }
    this._audioEnabled = false;
    this._updateAudioUI();
  }

  _audioErrorKey(error) {
    const known = {
      "asr-cloud-key-required": "audioCloudKeyRequired",
      "asr-host-permission-required": "audioPermissionRequired",
      "local-whisper-not-deployed": "audioLocalUnavailable",
    };
    return known[error] || "audioCaptureFailed";
  }

  _setAudioStatus(key) {
    if (this.elements.audioStatus) {
      this.elements.audioStatus.textContent = t(key);
    }
  }

  _updateAudioUI() {
    this.elements.btnAudio?.classList.toggle("active", this._audioEnabled);
    if (this.elements.btnAudio) {
      this.elements.btnAudio.textContent = t(
        this._audioEnabled ? "audioOn" : "audioOff",
      );
    }
    if (this.elements.audioStatus) {
      this.elements.audioStatus.textContent = t(
        this._audioEnabled ? "audioListening" : "audioStopped",
      );
    }
  }

  async _sendText() {
    const text = this.elements.textInput?.value?.trim();
    if (!text) return;
    const response = await this._sendMessage("sendText", { text });
    if (!response?.ok) {
      this._setStatus("unavailable");
      return;
    }
    this.elements.textInput.value = "";
    if (this.elements.btnSendText) {
      this.elements.btnSendText.textContent = t("sent");
      setTimeout(() => {
        if (this.elements.btnSendText) {
          this.elements.btnSendText.textContent = t("send");
        }
      }, 500);
    }
  }

  _scheduleSettingsSave() {
    clearTimeout(this._settingsTimer);
    this._settingsTimer = setTimeout(() => this._saveSettings(), 100);
  }

  async _saveSettings() {
    clearTimeout(this._settingsTimer);
    const updates = {
      targetSignLanguage: this.elements.signLanguage?.value || "csl",
      avatarSize: Number.parseInt(this.elements.avatarSize?.value || "260", 10),
      sourceLanguage: this.elements.sourceLanguage?.value || "auto",
      uiLocale: this.elements.uiLocale?.value || "auto",
    };
    this.config = await setConfig(updates);
    await this._sendMessage("updateConfig", { config: updates });
  }

  async _queryStatus() {
    const response = await this._sendMessage("getStatus");
    if (!response?.ok) {
      this._setStatus("unavailable");
      return;
    }
    this._isActive = response.active ?? false;
    const asrStatus = await this._sendRuntimeMessage({
      type: "ASR_GET_STATUS",
    });
    this._audioEnabled =
      asrStatus?.status === "running" &&
      asrStatus?.tabId === this._currentTabId;
    this._updateUI();
    this._updateAudioUI();
  }

  _setConfiguredLocale() {
    setLocale(this.config.uiLocale === "auto" ? null : this.config.uiLocale);
  }

  async _sendMessage(action, data = {}) {
    try {
      if (this._currentTabId) {
        return await chrome.tabs.sendMessage(this._currentTabId, {
          action,
          ...data,
        });
      }
    } catch {}
    return null;
  }

  async _sendRuntimeMessage(message) {
    try {
      return await chrome.runtime.sendMessage(message);
    } catch {
      return null;
    }
  }

  async _getCurrentTab() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    return tabs[0] || null;
  }
}

const popup = new SignBridgePopup();
popup.init().catch(console.error);
