/**
 * SignBridge 后台 Service Worker
 * 处理扩展安装生命周期。
 */

chrome.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === "install") {
    chrome.tabs.create({ url: chrome.runtime.getURL("popup/index.html") });
  }
});

console.log("[SignBridge] Service Worker initialized");
