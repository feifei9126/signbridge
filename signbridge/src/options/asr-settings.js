import {
  endpointPermissionPattern,
  getAsrConfig,
  LOCAL_MODEL_ORIGINS,
  normalizeAsrConfig,
  providerRequestConfig,
  setAsrConfig,
} from "../asr/asr-config.js";
import { transcribeAudio } from "../asr/transcription-client.js";
import { getConfig } from "../utils/config.js";
import { setLocale, t } from "../i18n/locales.js";

const elements = {
  providers: [...document.querySelectorAll('input[name="provider"]')],
  localPanel: document.getElementById("localPanel"),
  cloudPanel: document.getElementById("cloudPanel"),
  localModel: document.getElementById("localModel"),
  cloudEndpoint: document.getElementById("cloudEndpoint"),
  cloudApiKey: document.getElementById("cloudApiKey"),
  cloudModel: document.getElementById("cloudModel"),
  language: document.getElementById("language"),
  chunkSeconds: document.getElementById("chunkSeconds"),
  chunkValue: document.getElementById("chunkValue"),
  saveStatus: document.getElementById("saveStatus"),
  save: document.getElementById("btnSave"),
  test: document.getElementById("btnTest"),
  deploy: document.getElementById("btnDeploy"),
  deployProgress: document.getElementById("deployProgress"),
  deployStatus: document.getElementById("deployStatus"),
};

let deploymentPoll = null;

function applyTranslations() {
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((element) => {
    element.title = t(element.dataset.i18nTitle);
  });
}

function selectedProvider() {
  return elements.providers.find((input) => input.checked)?.value || "local";
}

function updateProviderPanels() {
  const local = selectedProvider() === "local";
  elements.localPanel.hidden = !local;
  elements.cloudPanel.hidden = local;
}

function collectConfig() {
  return normalizeAsrConfig({
    provider: selectedProvider(),
    localModel: elements.localModel.value,
    cloudEndpoint: elements.cloudEndpoint.value,
    cloudApiKey: elements.cloudApiKey.value,
    cloudModel: elements.cloudModel.value,
    language: elements.language.value,
    chunkSeconds: elements.chunkSeconds.value,
  });
}

function populate(config) {
  const provider = elements.providers.find(
    (input) => input.value === config.provider,
  );
  if (provider) provider.checked = true;
  elements.localModel.value = config.localModel;
  elements.cloudEndpoint.value = config.cloudEndpoint;
  elements.cloudApiKey.value = config.cloudApiKey;
  elements.cloudModel.value = config.cloudModel;
  elements.language.value = config.language;
  elements.chunkSeconds.value = config.chunkSeconds;
  elements.chunkValue.textContent = `${config.chunkSeconds}s`;
  updateProviderPanels();
}

async function ensureEndpointPermission(config) {
  const request = providerRequestConfig(config);
  if (request.provider === "local") return true;
  return chrome.permissions.request({
    origins: [endpointPermissionPattern(request.endpoint)],
  });
}

async function saveConfig() {
  try {
    const config = collectConfig();
    const granted = await ensureEndpointPermission(config);
    if (!granted) {
      elements.saveStatus.textContent = t("asrPermissionDenied");
      return null;
    }
    const saved = await setAsrConfig(config);
    elements.saveStatus.textContent = t("asrSaved");
    return saved;
  } catch (error) {
    console.error("[SignBridge] ASR settings save failed:", error);
    elements.saveStatus.textContent = t("asrInvalidConfig");
    return null;
  }
}

function silentWav() {
  const sampleRate = 16000;
  const samples = sampleRate;
  const buffer = new ArrayBuffer(44 + samples * 2);
  const view = new DataView(buffer);
  const write = (offset, text) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
  write(0, "RIFF");
  view.setUint32(4, 36 + samples * 2, true);
  write(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, samples * 2, true);
  return new Blob([buffer], { type: "audio/wav" });
}

function renderDeploymentStatus(state) {
  const modelMatches = state?.model === elements.localModel.value;
  const active = state?.status === "downloading" && modelMatches;
  elements.deploy.disabled = active;
  elements.deployProgress.hidden = !active;
  elements.deployProgress.value = Number(state?.progress || 0);

  if (state?.status === "ready" && modelMatches) {
    elements.deployStatus.textContent = t("asrDeployReady", {
      model: state.model,
    });
  } else if (active) {
    elements.deployStatus.textContent = t("asrDeploying", {
      progress: Math.round(Number(state?.progress || 0)),
    });
  } else if (state?.status === "error" && modelMatches) {
    elements.deployStatus.textContent = `${t("asrDeployFailed")}: ${state.error || ""}`;
  } else {
    elements.deployStatus.textContent = t("asrDeployRequired");
  }
  return active;
}

async function refreshDeploymentStatus() {
  const state = await chrome.runtime.sendMessage({ type: "ASR_LOCAL_STATUS" });
  const active = renderDeploymentStatus(state);
  if (!active && deploymentPoll) {
    clearInterval(deploymentPoll);
    deploymentPoll = null;
  }
  return state;
}

function startDeploymentPolling() {
  clearInterval(deploymentPoll);
  deploymentPoll = setInterval(() => {
    refreshDeploymentStatus().catch((error) => {
      console.error("[SignBridge] Local Whisper status failed:", error);
    });
  }, 500);
}

async function deployLocalModel() {
  elements.deploy.disabled = true;
  elements.deployStatus.textContent = t("asrRequestingModelPermission");
  try {
    const config = collectConfig();
    const granted = await chrome.permissions.request({
      origins: [...LOCAL_MODEL_ORIGINS],
    });
    if (!granted) {
      elements.deployStatus.textContent = t("asrPermissionDenied");
      elements.deploy.disabled = false;
      return;
    }
    await setAsrConfig(config);
    const state = await chrome.runtime.sendMessage({
      type: "ASR_LOCAL_DEPLOY",
      model: config.localModel,
    });
    if (!state?.ok) throw new Error(state?.error || "deployment-start-failed");
    renderDeploymentStatus(state);
    startDeploymentPolling();
  } catch (error) {
    console.error("[SignBridge] Local Whisper deployment failed:", error);
    elements.deployStatus.textContent = `${t("asrDeployFailed")}: ${error.message}`;
    elements.deploy.disabled = false;
  }
}

async function testConnection() {
  elements.test.disabled = true;
  elements.saveStatus.textContent = t("asrTesting");
  try {
    const config = await saveConfig();
    if (!config) return;
    const request = providerRequestConfig(config);
    if (request.provider === "local") {
      const state = await refreshDeploymentStatus();
      if (state?.status !== "ready" || state.model !== request.model) {
        throw new Error(t("asrDeployRequired"));
      }
    } else {
      await transcribeAudio(silentWav(), request);
    }
    elements.saveStatus.textContent = t("asrTestPassed");
  } catch (error) {
    console.error("[SignBridge] ASR connection test failed:", error);
    elements.saveStatus.textContent = `${t("asrTestFailed")}: ${error.message}`;
  } finally {
    elements.test.disabled = false;
  }
}

async function initialize() {
  const uiConfig = await getConfig();
  setLocale(uiConfig.uiLocale === "auto" ? null : uiConfig.uiLocale);
  applyTranslations();
  populate(await getAsrConfig());
  await refreshDeploymentStatus();
}

elements.providers.forEach((input) => {
  input.addEventListener("change", () => {
    updateProviderPanels();
    if (selectedProvider() === "local") refreshDeploymentStatus();
  });
});
elements.localModel.addEventListener("change", refreshDeploymentStatus);
elements.chunkSeconds.addEventListener("input", () => {
  elements.chunkValue.textContent = `${elements.chunkSeconds.value}s`;
});
elements.save.addEventListener("click", saveConfig);
elements.test.addEventListener("click", testConnection);
elements.deploy.addEventListener("click", deployLocalModel);

initialize().catch((error) => {
  console.error("[SignBridge] ASR settings failed to load:", error);
  elements.saveStatus.textContent = t("asrInvalidConfig");
});
