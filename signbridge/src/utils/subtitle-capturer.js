/**
 * SignBridge 字幕捕获器 v2
 * 从页面中捕获字幕/隐藏式字幕，实现语音+字幕双重识别
 *
 * FIX: 增加 Bilibili 特定的字幕选择器和 MutationObserver 改进
 */
export class SubtitleCapturer {
  constructor(options = {}) {
    this.onSubtitle = options.onSubtitle || (() => {});
    this.language = options.language || "zh-CN";
    this._active = false;
    this._observers = [];
    this._lastText = "";
    this._debounceTimer = null;
    this._sources = new Set();
    this._watchedTracks = new WeakSet();
    this._watchedElements = new WeakSet();
  }

  start() {
    if (this._active) return;
    this._active = true;
    this._sources.clear();
    this._watchedTracks = new WeakSet();
    this._watchedElements = new WeakSet();

    this._captureTrackElements();
    this._captureVideoTextTracks();
    this._captureDOMSubtitles();
    // Periodic scan for dynamically loaded video elements
    this._scanInterval = setInterval(() => {
      if (!this._active) return;
      this._captureTrackElements();
      this._captureVideoTextTracks();
    }, 2000);
  }

  _captureTrackElements() {
    document
      .querySelectorAll('track[kind="subtitles"], track[kind="captions"]')
      .forEach((track) => {
        if (track.track) {
          if (this._watchedTracks.has(track.track)) return;
          this._watchedTracks.add(track.track);
          if (track.track.mode === "disabled") track.track.mode = "hidden";
          const handler = () => {
            const cues = track.track.activeCues;
            if (!cues || cues.length === 0) return;
            const cue = cues[cues.length - 1];
            if (cue && cue.text && cue.text !== this._lastText) {
              this._lastText = cue.text;
              this._emitSubtitle(this._cleanText(cue.text), true);
            }
          };
          track.track.addEventListener("cuechange", handler);
          this._observers.push(() =>
            track.track?.removeEventListener("cuechange", handler),
          );
          this._sources.add("track:" + (track.track.language || "unknown"));
        }
      });
  }

  _captureVideoTextTracks() {
    document.querySelectorAll("video").forEach((video) => {
      if (!video.textTracks) return;
      for (let i = 0; i < video.textTracks.length; i++) {
        const textTrack = video.textTracks[i];
        if (textTrack.kind !== "subtitles" && textTrack.kind !== "captions")
          continue;
        if (this._watchedTracks.has(textTrack)) continue;
        if (
          this.language &&
          textTrack.language &&
          !textTrack.language.startsWith(this.language.split("-")[0])
        )
          continue;
        if (textTrack.mode === "disabled") textTrack.mode = "hidden";
        this._watchedTracks.add(textTrack);
        const handler = () => {
          const cues = textTrack.activeCues;
          if (!cues || cues.length === 0) return;
          const cue = cues[cues.length - 1];
          if (cue && cue.text && cue.text !== this._lastText) {
            this._lastText = cue.text;
            this._emitSubtitle(this._cleanText(cue.text), true);
          }
        };
        textTrack.addEventListener("cuechange", handler);
        this._observers.push(() =>
          textTrack?.removeEventListener("cuechange", handler),
        );
        this._sources.add("textTrack:" + (textTrack.language || "unknown"));
      }
    });
  }

  _captureDOMSubtitles() {
    const subtitleSelectors = [
      // B站
      ".bilibili-player-video-subtitle-text",
      ".subtitle-container .text",
      ".video-subtitle",
      "bpx-player-subtitle-panel-text",
      ".bpx-player-video-subtitle-text",
      ".bpx-player-subtitle-wrapper span",
      ".bpx-player-sending-text",
      // YouTube
      ".ytp-caption-segment",
      ".caption-window .captions-text span",
      ".ytp-caption-window-container .ytp-caption-segment",
      // Netflix
      ".player-timedtext-text-container span",
      ".player-timedtext-text",
      // Amazon Prime
      ".atvwebplayersdk-subtitle-text",
      ".atvwebplayersdk-captions-text",
      // Vimeo
      ".vp-captions-text",
      // 腾讯视频
      ".txp_subtitle_text",
      ".txp-subtitle-text",
      // 爱奇艺
      ".iqp-subtitle-text",
      ".iqp-subtitle",
      // 优酷
      ".yk-player-subtitle-text",
      ".youku-subtitle-text",
      // 抖音
      ".douyin-subtitle-text",
      ".xgplayer-text-track",
      // VideoJS
      ".vjs-text-track-display .vjs-text-track-cue div",
      ".vjs-text-track-cue > div",
      // Generic
      '[class*="subtitle"] [class*="text"]',
      '[class*="caption"] [class*="text"]',
      ".player-subtitle",
      ".subtitle-text",
    ];

    const combinedSelector = subtitleSelectors.join(",");
    document
      .querySelectorAll(combinedSelector)
      .forEach((element) => this._watchElement(element));

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === 1) {
            if (node.matches?.(combinedSelector)) this._watchElement(node);
            node
              .querySelectorAll(combinedSelector)
              .forEach((element) => this._watchElement(element));
          }
        }
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
    this._observers.push(() => observer.disconnect());
  }

  _watchElement(element) {
    if (this._watchedElements.has(element)) return;
    this._watchedElements.add(element);

    this._checkElementText(element);

    const textObserver = new MutationObserver(() => {
      this._checkElementText(element);
    });
    textObserver.observe(element, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    this._observers.push(() => textObserver.disconnect());
  }

  _checkElementText(element) {
    const text = element.textContent?.trim();
    if (text) this._checkText(text);
  }

  _checkText(text) {
    if (!text || text === this._lastText || text.length < 1) return;
    if (/^[\d:.,\s]+$/.test(text)) return;
    this._lastText = text;
    this._emitSubtitle(this._cleanText(text), true);
  }

  _cleanText(text) {
    return text
      .replace(/<[^>]+>/g, "")
      .replace(/\s+/g, " ")
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .trim();
  }

  _emitSubtitle(text, isFinal) {
    clearTimeout(this._debounceTimer);
    this._debounceTimer = setTimeout(() => {
      this.onSubtitle({
        text,
        isFinal,
        confidence: 0.9,
        timestamp: Date.now(),
        source: "subtitle",
      });
    }, 50);
  }

  get activeSources() {
    return [...this._sources];
  }

  stop() {
    this._active = false;
    clearTimeout(this._debounceTimer);
    clearInterval(this._scanInterval);
    for (const cleanup of this._observers) {
      try {
        cleanup();
      } catch {}
    }
    this._observers = [];
    this._sources.clear();
    this._watchedTracks = new WeakSet();
    this._watchedElements = new WeakSet();
    this._lastText = "";
  }

  destroy() {
    this.stop();
    this.onSubtitle = () => {};
  }
}

export default SubtitleCapturer;
