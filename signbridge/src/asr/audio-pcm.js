const WHISPER_SAMPLE_RATE = 16000;

function audioBufferToMono16Khz(audioBuffer) {
  const channelCount = audioBuffer.numberOfChannels;
  const inputLength = audioBuffer.length;
  const sourceRate = audioBuffer.sampleRate;
  const mono = new Float32Array(inputLength);

  for (let channel = 0; channel < channelCount; channel += 1) {
    const samples = audioBuffer.getChannelData(channel);
    for (let index = 0; index < inputLength; index += 1) {
      mono[index] += samples[index] / channelCount;
    }
  }

  if (sourceRate === WHISPER_SAMPLE_RATE) return mono;

  const ratio = sourceRate / WHISPER_SAMPLE_RATE;
  const outputLength = Math.max(1, Math.round(inputLength / ratio));
  const output = new Float32Array(outputLength);
  for (let index = 0; index < outputLength; index += 1) {
    const position = index * ratio;
    const left = Math.floor(position);
    const right = Math.min(left + 1, inputLength - 1);
    const weight = position - left;
    output[index] = mono[left] * (1 - weight) + mono[right] * weight;
  }
  return output;
}

async function decodeAudioBlob(blob, audioContext) {
  const encoded = await blob.arrayBuffer();
  const decoded = await audioContext.decodeAudioData(encoded.slice(0));
  return audioBufferToMono16Khz(decoded);
}

function hasAudibleSignal(samples, threshold = 0.002) {
  if (!samples.length) return false;
  let energy = 0;
  for (const sample of samples) energy += sample * sample;
  return Math.sqrt(energy / samples.length) >= threshold;
}

export {
  WHISPER_SAMPLE_RATE,
  audioBufferToMono16Khz,
  decodeAudioBlob,
  hasAudibleSignal,
};
