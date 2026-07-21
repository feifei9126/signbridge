/**
 * SignBridge 配置管理
 * 存储用户设置到 chrome.storage.sync
 */

const DEFAULTS = {
  enabled: false,
  sourceLanguage: "auto",
  targetSignLanguage: "csl",
  avatarStyle: "default",
  avatarSize: 260,
  avatarPosition: "bottom-right",
  avatarOpacity: 0.9,
  enableAutoDetect: true,
  enableSubtitles: true,
  voiceVolume: "medium",
  speed: 1.0,
  showAvatar: true,
  uiLocale: "auto",
};

const STORAGE_KEY = "signbridge_config";

export async function getConfig() {
  try {
    if (typeof chrome !== "undefined" && chrome.storage) {
      const result = await chrome.storage.sync.get(STORAGE_KEY);
      return { ...DEFAULTS, ...result[STORAGE_KEY] };
    }
  } catch (e) {
    // Fallback for non-extension context
  }
  return { ...DEFAULTS };
}

export async function setConfig(updates) {
  const current = await getConfig();
  const merged = { ...current, ...updates };
  try {
    if (typeof chrome !== "undefined" && chrome.storage) {
      await chrome.storage.sync.set({ [STORAGE_KEY]: merged });
    }
  } catch (e) {
    // Fallback
  }
  return merged;
}

export async function resetConfig() {
  try {
    if (typeof chrome !== "undefined" && chrome.storage) {
      await chrome.storage.sync.remove(STORAGE_KEY);
    }
  } catch (e) {}
  return { ...DEFAULTS };
}

export function getDefaultConfig() {
  return { ...DEFAULTS };
}
