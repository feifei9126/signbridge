/**
 * SignBridge 后台 Service Worker
 * 管理全局状态，处理跨标签页消息，管理配置
 */

import { getConfig, setConfig, resetConfig } from "../utils/config.js";

// 活跃标签页跟踪
const activeTabs = new Map();

// 安装/激活事件
chrome.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === "install") {
    // 打开欢迎页或设置页
    chrome.tabs.create({ url: chrome.runtime.getURL("popup/index.html") });
  }

  // 注入内容脚本到已有标签页
  const tabs = await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] });
  for (const tab of tabs) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["content/injector.js"],
      });
      await chrome.scripting.insertCSS({
        target: { tabId: tab.id },
        files: ["content/overlay.css"],
      });
    } catch (e) {
      // 忽略注入错误（如特权页面）
    }
  }
});

// 监听来自 content script / popup 的消息
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const tabId = sender.tab?.id;

  switch (message.action) {
    case "getConfig":
      getConfig().then(sendResponse);
      return true;

    case "setConfig":
      setConfig(message.config).then(sendResponse);
      // 广播配置更新到所有标签页
      broadcastToTabs({
        action: "updateConfig",
        config: message.config,
      });
      return true;

    case "resetConfig":
      resetConfig().then(sendResponse);
      broadcastToTabs({ action: "updateConfig", config: {} });
      return true;

    case "getStatus": {
      const status = {
        activeTabs: Array.from(activeTabs.entries()).map(([id, info]) => ({
          tabId: id,
          ...info,
        })),
        hasActiveTranslation: Array.from(activeTabs.values()).some(
          (t) => t.translating,
        ),
      };
      sendResponse(status);
      return true;
    }

    case "tabActive": {
      if (tabId) {
        activeTabs.set(tabId, {
          url: sender.tab?.url,
          title: sender.tab?.title,
          translating: message.translating || false,
          lastActive: Date.now(),
        });
      }
      sendResponse({ ok: true });
      return true;
    }

    case "tabInactive": {
      if (tabId) {
        activeTabs.delete(tabId);
      }
      sendResponse({ ok: true });
      return true;
    }

    case "toggleTranslation": {
      // 转发到指定标签页
      const targetTabId = message.tabId || tabId;
      if (targetTabId) {
        chrome.tabs.sendMessage(targetTabId, { action: "toggle" });
      }
      sendResponse({ ok: true });
      return true;
    }
  }
});

// 标签页更新时重新注入
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "loading" && tab.url?.match(/^https?:\/\//)) {
    // 页面重新加载时清理跟踪
    activeTabs.delete(tabId);
  }

  if (changeInfo.status === "complete" && tab.url?.match(/^https?:\/\//)) {
    // 注入内容脚本
    chrome.scripting
      .executeScript({
        target: { tabId },
        files: ["content/injector.js"],
      })
      .catch(() => {});

    chrome.scripting
      .insertCSS({
        target: { tabId },
        files: ["content/overlay.css"],
      })
      .catch(() => {});
  }
});

// 标签页关闭时清理
chrome.tabs.onRemoved.addListener((tabId) => {
  activeTabs.delete(tabId);
});

// 广播消息到所有活跃标签页
async function broadcastToTabs(message) {
  const tabs = await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] });
  for (const tab of tabs) {
    try {
      await chrome.tabs.sendMessage(tab.id, message);
    } catch (e) {
      // 忽略
    }
  }
}

// 保持 Service Worker 活跃
chrome.runtime.onConnect.addListener((port) => {
  // 保持连接
  port.onDisconnect.addListener(() => {});
});

console.log("[SignBridge] Service Worker initialized");
