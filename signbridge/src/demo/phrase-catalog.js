import { demoTextKey, motionSource, planDemoText } from "./demo-motion.js";

const COMPOSITION_PROPOSALS = [
  { id: "composed-hello-thanks", text: "你好，谢谢", category: "daily" },
  { id: "composed-welcome-you", text: "欢迎你", category: "daily" },
  { id: "composed-thank-you", text: "谢谢你", category: "daily" },
  { id: "composed-i-am-good", text: "我很好", category: "daily" },
  { id: "composed-you-are-good", text: "你很好", category: "daily" },
  { id: "composed-he-is-good", text: "他很好", category: "daily" },
  { id: "composed-we-are-good", text: "我们都很好", category: "daily" },
  { id: "composed-i-am-happy", text: "我很开心", category: "daily" },
  { id: "composed-i-love-you", text: "我爱你", category: "daily" },
  { id: "composed-you-love-me", text: "你爱我", category: "daily" },
  { id: "composed-i-am-also-happy", text: "我也很开心", category: "daily" },
  { id: "composed-please-help-me", text: "请帮助我", category: "help" },
  { id: "composed-please-help-me-2", text: "请你帮助我", category: "help" },
  { id: "composed-i-can-help-you", text: "我可以帮助你", category: "help" },
  { id: "composed-you-can-help-me", text: "你可以帮助我", category: "help" },
  { id: "composed-i-want-help-you", text: "我想帮助你", category: "help" },
  { id: "composed-you-want-help-me", text: "你想帮助我", category: "help" },
  { id: "composed-i-help-you", text: "我帮助你", category: "help" },
  { id: "composed-we-help-you", text: "我们帮助你", category: "help" },
  { id: "composed-please-speak", text: "请你说", category: "help" },
  { id: "composed-please-look", text: "请你看", category: "help" },
  { id: "composed-you-can-speak", text: "你可以说", category: "help" },
  { id: "composed-what-can-you-do", text: "你可以做什么", category: "help" },
  { id: "composed-who-are-you", text: "你是谁", category: "questions" },
  { id: "composed-who-is-he", text: "他是谁", category: "questions" },
  { id: "composed-what-is-this", text: "这是什么", category: "questions" },
  {
    id: "composed-what-is-this-one",
    text: "这个是什么",
    category: "questions",
  },
  { id: "composed-what-is-that", text: "那是什么", category: "questions" },
  {
    id: "composed-what-is-that-one",
    text: "那个是什么",
    category: "questions",
  },
  { id: "composed-what-do-you-want", text: "你要什么", category: "questions" },
  {
    id: "composed-what-do-you-want-2",
    text: "你想要什么",
    category: "questions",
  },
  {
    id: "composed-what-do-you-know",
    text: "你知道什么",
    category: "questions",
  },
  { id: "composed-i-know-this", text: "我知道这个", category: "questions" },
  { id: "composed-you-know-this", text: "你知道这个", category: "questions" },
  { id: "composed-how-do-you-go", text: "你怎么去", category: "questions" },
  { id: "composed-where-do-you-go", text: "你去哪里", category: "questions" },
  { id: "composed-what-do-you-see", text: "你看什么", category: "questions" },
  { id: "composed-what-do-you-say", text: "你说什么", category: "questions" },
  { id: "composed-i-do-not-know", text: "我不知道", category: "questions" },
  { id: "composed-you-do-not-know", text: "你不知道", category: "questions" },
  { id: "composed-i-do-not-understand", text: "我不懂", category: "questions" },
  {
    id: "composed-you-do-not-understand",
    text: "你不懂",
    category: "questions",
  },
  {
    id: "composed-i-cannot-understand",
    text: "我看不懂",
    category: "questions",
  },
  {
    id: "composed-i-do-not-know-this",
    text: "我不知道这个",
    category: "questions",
  },
  { id: "composed-i-go-now", text: "我现在去", category: "travel" },
  { id: "composed-we-go-now", text: "我们现在去", category: "travel" },
  { id: "composed-you-come-now", text: "你现在来", category: "travel" },
  { id: "composed-you-come", text: "你要来", category: "travel" },
  { id: "composed-you-go", text: "你要去", category: "travel" },
  { id: "composed-i-also-go", text: "我也要去", category: "travel" },
  { id: "composed-please-come", text: "请你来", category: "travel" },
  { id: "composed-you-can-come", text: "你可以来", category: "travel" },
  { id: "composed-you-can-go", text: "你可以去", category: "travel" },
].map((phrase) => ({
  ...phrase,
  source: "composition",
  training_data_member: false,
  training_ready: false,
}));

// Advertise only fully matched authored drafts under the shared word boundaries.
// The historical proposals stay in source; unsupported combinations are not sold
// as playable phrases and no dictionary entries are invented to make them pass.
export const COMPOSED_PHRASES = COMPOSITION_PROPOSALS.filter((phrase) => {
  const plan = planDemoText(phrase.text, "dictionary");
  return !plan.unmatched && !plan.truncated && plan.items.length >= 2;
});

export function buildDemoPhraseCatalog(clips = []) {
  const priority = { t08: 0, candidate: 1, experimental: 2, composition: 3 };
  const entries = [
    ...clips.map((clip) => ({
      id: clip.id,
      text: clip.text,
      source: motionSource(clip),
      training_ready: false,
    })),
    ...COMPOSED_PHRASES,
  ].sort((a, b) => priority[a.source] - priority[b.source]);
  const keys = new Set();
  return entries.filter((entry) => {
    const key = demoTextKey(entry.text);
    if (!key || keys.has(key)) return false;
    keys.add(key);
    return true;
  });
}
