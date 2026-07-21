// BUILD: 1784252939651
/**
 * 手语数据 v7 — 结构化词典 + 手语参数元数据
 * 借鉴 VLibras 的词典设计：gloss 标准名、手形/位置/运动分类、可检索标签
 */
import { deg, frm } from "./pose-engine.js";

// ===== 手形原子 (Handshape Primitives) =====
function handShape(name) {
  const d = Math.PI / 180;
  const shapes = {
    relax: {},
    fist: {
      rthumb: { x: -40 * d, y: 0, z: 0 },
      rindex: { x: -110 * d, y: 0, z: 0 },
      rmiddle: { x: -110 * d, y: 0, z: 0 },
      rring: { x: -110 * d, y: 0, z: 0 },
      rpinky: { x: -110 * d, y: 0, z: 0 },
      lthumb: { x: -40 * d, y: 0, z: 0 },
      lindex: { x: -110 * d, y: 0, z: 0 },
      lmiddle: { x: -110 * d, y: 0, z: 0 },
      lring: { x: -110 * d, y: 0, z: 0 },
      lpinky: { x: -110 * d, y: 0, z: 0 },
    },
    flat: {
      rthumb: { x: 30 * d, y: 0, z: 0 },
      rindex: { x: 30 * d, y: 0, z: 0 },
      rmiddle: { x: 30 * d, y: 0, z: 0 },
      rring: { x: 30 * d, y: 0, z: 0 },
      rpinky: { x: 30 * d, y: 0, z: 0 },
      lthumb: { x: 30 * d, y: 0, z: 0 },
      lindex: { x: 30 * d, y: 0, z: 0 },
      lmiddle: { x: 30 * d, y: 0, z: 0 },
      lring: { x: 30 * d, y: 0, z: 0 },
      lpinky: { x: 30 * d, y: 0, z: 0 },
    },
    point: {
      rthumb: { x: -40 * d, y: 0, z: 0 },
      rindex: { x: 0, y: 0, z: 0 },
      rmiddle: { x: -110 * d, y: 0, z: 0 },
      rring: { x: -110 * d, y: 0, z: 0 },
      rpinky: { x: -110 * d, y: 0, z: 0 },
      lthumb: { x: -40 * d, y: 0, z: 0 },
      lindex: { x: 0, y: 0, z: 0 },
      lmiddle: { x: -110 * d, y: 0, z: 0 },
      lring: { x: -110 * d, y: 0, z: 0 },
      lpinky: { x: -110 * d, y: 0, z: 0 },
    },
    thumbUp: {
      rthumb: { x: 0, y: 63 * d, z: 30 * d },
      rindex: { x: -110 * d, y: 0, z: 0 },
      rmiddle: { x: -110 * d, y: 0, z: 0 },
      rring: { x: -110 * d, y: 0, z: 0 },
      rpinky: { x: -110 * d, y: 0, z: 0 },
      lthumb: { x: 0, y: 63 * d, z: 30 * d },
      lindex: { x: -110 * d, y: 0, z: 0 },
      lmiddle: { x: -110 * d, y: 0, z: 0 },
      lring: { x: -110 * d, y: 0, z: 0 },
      lpinky: { x: -110 * d, y: 0, z: 0 },
    },
    peace: {
      rthumb: { x: -40 * d, y: 0, z: 0 },
      rindex: { x: 0, y: 0, z: 0 },
      rmiddle: { x: 0, y: 0, z: 0 },
      rring: { x: -110 * d, y: 0, z: 0 },
      rpinky: { x: -110 * d, y: 0, z: 0 },
    },
    ok: {
      rthumb: { x: -20 * d, y: 30 * d, z: 0 },
      rindex: { x: -90 * d, y: 0, z: 0 },
      rmiddle: { x: -90 * d, y: 0, z: 0 },
      rring: { x: -90 * d, y: 0, z: 0 },
      rpinky: { x: -90 * d, y: 0, z: 0 },
    },
  };
  return shapes[name] || shapes.relax;
}

// ===== 手势构建器 =====
// 手臂参数: [shX,shY,shZ, uaX,uaY,uaZ, faX,faY,faZ, hX,hY,hZ]
function gesture(arm, shape, lArm, lShape) {
  const p = {};
  p.rShoulder = deg(arm[0] || 0, arm[1] || 0, arm[2] || 0);
  p.rUpperArm = deg(arm[3] || 0, arm[4] || 0, arm[5] || 0);
  p.rForearm = deg(arm[6] || 0, arm[7] || 0, arm[8] || 0);
  p.rHand = deg(arm[9] || 0, arm[10] || 0, arm[11] || 0);
  if (lArm) {
    p.lShoulder = deg(lArm[0] || 0, lArm[1] || 0, lArm[2] || 0);
    p.lUpperArm = deg(lArm[3] || 0, lArm[4] || 0, lArm[5] || 0);
    p.lForearm = deg(lArm[6] || 0, lArm[7] || 0, lArm[8] || 0);
    p.lHand = deg(lArm[9] || 0, lArm[10] || 0, lArm[11] || 0);
  }
  if (shape) {
    const s = handShape(shape);
    for (const k in s) p[k] = s[k];
  }
  if (lShape) {
    const s = handShape(lShape);
    for (const k in s) p[k] = s[k];
  }
  return p;
}

// 常用手臂简写
const A = [0, 0, 0, 35, 50, -15, 15, 0, 0, 0, 0, 0];
const AH = [0, 0, 0, 40, 50, -15, 20, 0, 0, -90, 0, 0];
const AL = [0, 0, 0, 30, 50, -10, 10, 0, 0, 0, 0, 0];
const AT = [0, 0, 0, 55, 5, -10, 20, 0, 0, 0, 10, 10];
const AW = [10, 20, 0, 35, 20, 0, 15, 5, 0, 10, 0, 0];
const AWL = [10, -20, 0, 35, -5, 0, 15, -5, 0, 10, 0, 0];

const AP = [0, 0, 0, 40, 50, -15, 20, 0, 0, 0, 0, 0];
const AS = [0, 0, 0, 40, 30, -15, 15, 0, 0, 0, 0, 0];
const AD = [0, 0, 0, 35, 40, -10, 20, 0, 0, 0, -5, 0];
const APL = [0, 0, 0, 40, 50, -15, 20, 0, 0, 5, 0, 0];
const AW2 = [15, 20, 0, 50, 40, -15, 25, 5, 0, 5, 0, 0];

// ===== 结构化手语词典 =====
// 借鉴 VLibras 格式: id + gloss + texts + tags + frames + metadata
const SIGNS = {
  csl_hello: {
    id: "csl_hello",
    gloss: "你好",
    texts: ["你好", "您好", "嗨", "hello", "hi"],
    tags: ["greeting"],
    frames: [frm(gesture(A, "point"), 0.6), frm(gesture(A, "thumbUp"), 0.7)],
    meta: { handshape: "point+thumbUp", location: "chest", movement: "none" },
  },
  csl_thanks: {
    id: "csl_thanks",
    gloss: "谢谢",
    texts: ["谢谢", "多谢", "感谢", "thanks"],
    tags: ["polite"],
    frames: [frm(gesture(AT, "fist"), 0.8)],
    meta: { handshape: "fist", location: "chest", movement: "nod" },
  },
  csl_yes: {
    id: "csl_yes",
    gloss: "是",
    texts: ["是", "对", "正确", "yes", "ok"],
    tags: ["confirm"],
    frames: [frm(gesture(A, "point"), 0.6)],
    meta: { handshape: "point", location: "chest", movement: "nod" },
  },
  csl_no: {
    id: "csl_no",
    gloss: "不",
    texts: ["不", "没", "没有", "别", "no", "not"],
    tags: ["negation"],
    frames: [
      frm(gesture([0, 0, 0, 40, 50, -15, 25, 0, 0, 5, 0, 0], "point"), 0.5),
    ],
    meta: { handshape: "point", location: "chest", movement: "sway" },
  },
  csl_good: {
    id: "csl_good",
    gloss: "好",
    texts: ["好", "棒", "优秀", "good", "great"],
    tags: ["positive"],
    frames: [frm(gesture(A, "thumbUp"), 0.7)],
    meta: { handshape: "thumbUp", location: "chest", movement: "none" },
  },
  csl_me: {
    id: "csl_me",
    gloss: "我",
    texts: ["我", "自己", "me", "I"],
    tags: ["pronoun"],
    frames: [
      frm(gesture([0, 0, 0, 35, 50, -15, 25, 0, 0, 5, 0, 0], "point"), 0.6),
    ],
    meta: { handshape: "point", location: "chest", movement: "self" },
  },
  csl_you: {
    id: "csl_you",
    gloss: "你",
    texts: ["你", "您", "you"],
    tags: ["pronoun"],
    frames: [
      frm(gesture([0, 0, 0, 40, 50, -15, 25, 0, 0, 5, 0, 0], "point"), 0.6),
    ],
    meta: { handshape: "point", location: "forward", movement: "none" },
  },
  csl_help: {
    id: "csl_help",
    gloss: "帮助",
    texts: ["帮助", "帮忙", "帮", "help"],
    tags: ["action"],
    frames: [
      frm(gesture([0, 0, 0, 40, 40, -10, 25, 0, 0, -5, 5, 0], "flat"), 0.7),
    ],
    meta: { handshape: "flat", location: "chest", movement: "support" },
  },
  csl_welcome: {
    id: "csl_welcome",
    gloss: "欢迎",
    texts: ["欢迎", "welcome"],
    tags: ["greeting"],
    frames: [frm(gesture(AW, "flat", AWL, "flat"), 0.8)],
    meta: { handshape: "flat", location: "side", movement: "open" },
  },
  csl_love: {
    id: "csl_love",
    gloss: "爱",
    texts: ["爱", "喜欢", "love", "like"],
    tags: ["emotion"],
    frames: [frm(gesture(AL, "fist", AL, "fist"), 0.8)],
    meta: { handshape: "fist", location: "heart", movement: "none" },
  },
  csl_goodbye: {
    id: "csl_goodbye",
    gloss: "再见",
    texts: ["再见", "拜拜", "bye", "goodbye"],
    tags: ["greeting"],
    frames: [
      frm(gesture([0, 0, 0, 40, 50, -15, 25, 0, 0, 5, 0, 0], "flat"), 0.6),
      frm(gesture([0, 0, 0, 40, 50, -15, 25, 0, 0, 5, 0, 0], "flat"), 0.4),
      frm(gesture([0, 0, 0, 40, 50, -15, 25, 0, 0, 5, 0, 0], "flat"), 0.4),
    ],
    meta: { handshape: "flat", location: "side", movement: "wave" },
  },
  csl_happy: {
    id: "csl_happy",
    gloss: "开心",
    texts: ["开心", "高兴", "快乐", "happy"],
    tags: ["emotion"],
    frames: [
      frm(gesture([0, 0, 0, 40, 50, -15, 25, 0, 0, 0, 0, 0], "flat"), 0.6),
    ],
    meta: { handshape: "flat", location: "chest", movement: "none" },
  },
  csl_true: {
    id: "csl_true",
    gloss: "真",
    texts: ["真", "真的", "确实", "true", "really"],
    tags: ["confirm"],
    frames: [frm(gesture(A, "point"), 0.5)],
    meta: { handshape: "point", location: "chest", movement: "none" },
  },
  csl_too: {
    id: "csl_too",
    gloss: "太",
    texts: ["太", "很", "非常", "very", "too"],
    tags: ["degree"],
    frames: [frm(gesture(A, "thumbUp"), 0.5)],
    meta: { handshape: "thumbUp", location: "chest", movement: "none" },
  },
  csl_what: {
    id: "csl_what",
    gloss: "什么",
    texts: ["什么", "啥", "what"],
    tags: ["question"],
    frames: [frm(gesture(A, "flat"), 0.5)],
    meta: { handshape: "flat", location: "chest", movement: "none" },
  },

  csl_he: {
    id: "csl_he",
    gloss: "他",
    texts: ["他", "她", "它", "he", "she"],
    tags: ["pronoun"],
    frames: [
      frm(gesture([0, 0, 0, 40, 60, -15, 20, 0, 0, 5, 0, 0], "point"), 0.6),
    ],
    meta: { handshape: "point", location: "side", movement: "none" },
  },
  csl_we: {
    id: "csl_we",
    gloss: "我们",
    texts: ["我们", "咱们", "we", "us"],
    tags: ["pronoun"],
    frames: [
      frm(gesture([0, 0, 0, 30, 40, -10, 20, 0, 0, 5, 0, 0], "point"), 0.7),
    ],
    meta: { handshape: "point", location: "chest", movement: "arc" },
  },
  csl_this: {
    id: "csl_this",
    gloss: "这",
    texts: ["这", "这个", "this"],
    tags: ["demonstrative"],
    frames: [frm(gesture(AD, "point"), 0.5)],
    meta: { handshape: "point", location: "down", movement: "none" },
  },
  csl_that: {
    id: "csl_that",
    gloss: "那",
    texts: ["那", "那个", "that"],
    tags: ["demonstrative"],
    frames: [
      frm(gesture([0, 0, 0, 40, 60, -15, 20, 0, 0, 5, 0, 0], "point"), 0.5),
    ],
    meta: { handshape: "point", location: "forward", movement: "none" },
  },
  csl_who: {
    id: "csl_who",
    gloss: "谁",
    texts: ["谁", "who"],
    tags: ["question"],
    frames: [frm(gesture(A, "point"), 0.6)],
    meta: { handshape: "point", location: "chest", movement: "none" },
  },
  csl_how: {
    id: "csl_how",
    gloss: "怎么",
    texts: ["怎么", "怎样", "how"],
    tags: ["question"],
    frames: [frm(gesture(A, "flat"), 0.6)],
    meta: { handshape: "flat", location: "chest", movement: "none" },
  },
  csl_where: {
    id: "csl_where",
    gloss: "哪",
    texts: ["哪", "哪里", "where"],
    tags: ["question"],
    frames: [frm(gesture(A, "point"), 0.6)],
    meta: { handshape: "point", location: "chest", movement: "none" },
  },
  csl_have: {
    id: "csl_have",
    gloss: "有",
    texts: ["有", "have", "has"],
    tags: ["state"],
    frames: [frm(gesture(A, "thumbUp"), 0.6)],
    meta: { handshape: "thumbUp", location: "chest", movement: "none" },
  },
  csl_can: {
    id: "csl_can",
    gloss: "可以",
    texts: ["可以", "能", "can", "may"],
    tags: ["modal"],
    frames: [frm(gesture(A, "ok"), 0.6)],
    meta: { handshape: "ok", location: "chest", movement: "nod" },
  },
  csl_want: {
    id: "csl_want",
    gloss: "要",
    texts: ["要", "想", "want", "need"],
    tags: ["modal"],
    frames: [frm(gesture(A, "flat"), 0.6)],
    meta: { handshape: "flat", location: "chest", movement: "pull" },
  },
  csl_come: {
    id: "csl_come",
    gloss: "来",
    texts: ["来", "过来", "come"],
    tags: ["action"],
    frames: [frm(gesture(APL, "flat"), 0.6)],
    meta: { handshape: "flat", location: "side", movement: "beckon" },
  },
  csl_go: {
    id: "csl_go",
    gloss: "去",
    texts: ["去", "走", "go"],
    tags: ["action"],
    frames: [
      frm(gesture([0, 0, 0, 40, 50, -15, 25, 0, 0, 0, 0, 0], "flat"), 0.5),
    ],
    meta: { handshape: "flat", location: "forward", movement: "push" },
  },
  csl_say: {
    id: "csl_say",
    gloss: "说",
    texts: ["说", "讲", "say", "speak"],
    tags: ["action"],
    frames: [
      frm(gesture([0, 0, 0, 35, 40, -15, 20, 0, 0, -5, 0, 0], "flat"), 0.6),
    ],
    meta: { handshape: "flat", location: "mouth", movement: "none" },
  },
  csl_see: {
    id: "csl_see",
    gloss: "看",
    texts: ["看", "见", "see", "look"],
    tags: ["action"],
    frames: [
      frm(gesture([0, 0, 0, 35, 35, -10, 20, 0, 0, 0, 0, 0], "point"), 0.6),
    ],
    meta: { handshape: "point", location: "eyes", movement: "none" },
  },
  csl_know: {
    id: "csl_know",
    gloss: "知道",
    texts: ["知道", "懂", "know", "understand"],
    tags: ["cognition"],
    frames: [frm(gesture(A, "point"), 0.6)],
    meta: { handshape: "point", location: "temple", movement: "none" },
  },
  csl_big: {
    id: "csl_big",
    gloss: "大",
    texts: ["大", "big", "large"],
    tags: ["size"],
    frames: [frm(gesture(AW2, "flat"), 0.6)],
    meta: { handshape: "flat", location: "side", movement: "spread" },
  },
  csl_small: {
    id: "csl_small",
    gloss: "小",
    texts: ["小", "small", "little"],
    tags: ["size"],
    frames: [
      frm(gesture([0, 0, 0, 35, 30, -10, 20, 0, 0, 0, 0, 0], "flat"), 0.5),
    ],
    meta: { handshape: "flat", location: "chest", movement: "close" },
  },
  csl_many: {
    id: "csl_many",
    gloss: "多",
    texts: ["多", "很多", "many", "much"],
    tags: ["quantity"],
    frames: [frm(gesture(A, "flat"), 0.5)],
    meta: { handshape: "flat", location: "chest", movement: "none" },
  },
  csl_up: {
    id: "csl_up",
    gloss: "上",
    texts: ["上", "up", "above"],
    tags: ["direction"],
    frames: [
      frm(gesture([0, 0, 0, 40, 40, -15, 15, 0, 0, 10, 0, 0], "point"), 0.5),
    ],
    meta: { handshape: "point", location: "up", movement: "none" },
  },
  csl_down: {
    id: "csl_down",
    gloss: "下",
    texts: ["下", "down", "below"],
    tags: ["direction"],
    frames: [
      frm(gesture([0, 0, 0, 35, 40, -15, 25, 0, 0, -5, 0, 0], "point"), 0.5),
    ],
    meta: { handshape: "point", location: "down", movement: "none" },
  },
  csl_now: {
    id: "csl_now",
    gloss: "现在",
    texts: ["现在", "now"],
    tags: ["time"],
    frames: [frm(gesture(A, "flat"), 0.5)],
    meta: { handshape: "flat", location: "chest", movement: "none" },
  },
  csl_today: {
    id: "csl_today",
    gloss: "今天",
    texts: ["今天", "today"],
    tags: ["time"],
    frames: [frm(gesture(A, "point"), 0.5)],
    meta: { handshape: "point", location: "chest", movement: "none" },
  },
  csl_also: {
    id: "csl_also",
    gloss: "也",
    texts: ["也", "also", "too"],
    tags: ["conjunction"],
    frames: [frm(gesture(A, "point"), 0.5)],
    meta: { handshape: "point", location: "chest", movement: "none" },
  },
  csl_all: {
    id: "csl_all",
    gloss: "都",
    texts: ["都", "全部", "all"],
    tags: ["quantity"],
    frames: [frm(gesture(AW2, "flat", AWL, "flat"), 0.6)],
    meta: { handshape: "flat", location: "side", movement: "arc" },
  },
  csl_but: {
    id: "csl_but",
    gloss: "但是",
    texts: ["但是", "但", "but"],
    tags: ["conjunction"],
    frames: [frm(gesture(A, "point"), 0.6)],
    meta: { handshape: "point", location: "chest", movement: "none" },
  },
  csl_if: {
    id: "csl_if",
    gloss: "如果",
    texts: ["如果", "要是", "if"],
    tags: ["conjunction"],
    frames: [frm(gesture(A, "flat"), 0.5)],
    meta: { handshape: "flat", location: "chest", movement: "none" },
  },
  csl_very: {
    id: "csl_very",
    gloss: "很",
    texts: ["很", "非常", "very", "quite"],
    tags: ["degree"],
    frames: [frm(gesture(A, "thumbUp"), 0.5)],
    meta: { handshape: "thumbUp", location: "chest", movement: "none" },
  },
  csl_and: {
    id: "csl_and",
    gloss: "和",
    texts: ["和", "跟", "与", "and"],
    tags: ["conjunction"],
    frames: [
      frm(gesture([0, 0, 0, 35, 40, -15, 20, 0, 0, 5, 0, 0], "flat"), 0.5),
    ],
    meta: { handshape: "flat", location: "chest", movement: "none" },
  },
  csl_new: {
    id: "csl_new",
    gloss: "新",
    texts: ["新", "new"],
    tags: ["quality"],
    frames: [frm(gesture(APL, "flat"), 0.5)],
    meta: { handshape: "flat", location: "chest", movement: "none" },
  },
  csl_old: {
    id: "csl_old",
    gloss: "老",
    texts: ["老", "旧", "old"],
    tags: ["quality"],
    frames: [frm(gesture(AD, "fist"), 0.5)],
    meta: { handshape: "fist", location: "chest", movement: "none" },
  },
  csl_one: {
    id: "csl_one",
    gloss: "一",
    texts: ["一", "one"],
    tags: ["number"],
    frames: [frm(gesture(A, "point"), 0.4)],
    meta: { handshape: "point", location: "chest", movement: "none" },
  },
  csl_two: {
    id: "csl_two",
    gloss: "二",
    texts: ["二", "两", "two"],
    tags: ["number"],
    frames: [frm(gesture(A, "peace"), 0.4)],
    meta: { handshape: "peace", location: "chest", movement: "none" },
  },
  csl_three: {
    id: "csl_three",
    gloss: "三",
    texts: ["三", "three"],
    tags: ["number"],
    frames: [frm(gesture(A, "ok"), 0.4)],
    meta: { handshape: "ok", location: "chest", movement: "none" },
  },
  csl_please: {
    id: "csl_please",
    gloss: "请",
    texts: ["请", "please"],
    tags: ["polite"],
    frames: [frm(gesture(APL, "flat"), 0.7)],
    meta: { handshape: "flat", location: "chest", movement: "none" },
  },
  csl_do: {
    id: "csl_do",
    gloss: "做",
    texts: ["做", "干", "do"],
    tags: ["action"],
    frames: [frm(gesture(A, "fist"), 0.5)],
    meta: { handshape: "fist", location: "chest", movement: "none" },
  },
  csl_people: {
    id: "csl_people",
    gloss: "人",
    texts: ["人", "person", "people"],
    tags: ["noun"],
    frames: [
      frm(gesture([0, 0, 0, 35, 50, -15, 25, 0, 0, 0, 0, 0], "point"), 0.6),
    ],
    meta: { handshape: "point", location: "side", movement: "none" },
  },
  csl_self: {
    id: "csl_self",
    gloss: "自己",
    texts: ["自己", "self"],
    tags: ["pronoun"],
    frames: [frm(gesture(AL, "fist", AL, "fist"), 0.6)],
    meta: { handshape: "fist", location: "chest", movement: "self" },
  },
};

// ===== 单字手势（特殊/备用） =====
const SINGLE_CHARS = {};
function addChar(c, frames) {
  SINGLE_CHARS[c] = frames;
}
addChar("你", [frm(gesture(A, "point"), 0.6)]);
addChar("好", [frm(gesture(A, "thumbUp"), 0.7)]);
addChar("谢", [frm(gesture(AT, "fist"), 0.8)]);
addChar("我", [
  frm(gesture([0, 0, 0, 35, 50, -15, 25, 0, 0, 5, 0, 0], "point"), 0.6),
]);
addChar("爱", [frm(gesture(AL, "fist", AL, "fist"), 0.8)]);
addChar("是", [frm(gesture(A, "point"), 0.6)]);
addChar("对", [frm(gesture(A, "point"), 0.6)]);
addChar("不", [
  frm(gesture([0, 0, 0, 40, 50, -15, 25, 0, 0, 5, 0, 0], "point"), 0.5),
]);
addChar("帮", [
  frm(gesture([0, 0, 0, 40, 40, -10, 25, 0, 0, -5, 5, 0], "flat"), 0.6),
]);
addChar("助", [
  frm(gesture([0, 0, 0, 40, 40, -10, 25, 0, 0, -5, 5, 0], "flat"), 0.6),
]);
addChar("再", [
  frm(gesture([0, 0, 0, 40, 50, -15, 25, 0, 0, 5, 0, 0], "flat"), 0.6),
]);
addChar("见", [
  frm(gesture([0, 0, 0, 40, 50, -15, 25, 0, 0, 5, 0, 0], "flat"), 0.6),
]);
addChar("欢", [frm(gesture(AW, "flat", AWL, "flat"), 0.6)]);
addChar("迎", [frm(gesture(AW, "flat", AWL, "flat"), 0.6)]);
addChar("喜", [frm(gesture(AL, "fist", AL, "fist"), 0.7)]);
addChar(" ", [frm({}, 0.3)]);

// ===== 构建查找索引 =====
function buildLookup() {
  const lookup = {};
  // Multi-word signs from SIGNS
  for (const [id, sign] of Object.entries(SIGNS)) {
    for (const text of sign.texts) {
      // Keep longest text match
      if (!lookup[text] || text.length > (lookup[text].length || 0)) {
        lookup[text] = sign.frames;
      }
    }
  }
  return lookup;
}

// ===== 文本规范化 =====
function normalizeText(text) {
  if (!text) return "";
  return text
    .replace(/[，。！？、；：""''（）【】《》\s]+/g, " ") // 标点→空格
    .replace(/[^\u4e00-\u9fff\u3400-\u4dbf a-zA-Z0-9]/g, "") // 保留中文+英文+数字
    .replace(/\s+/g, " ")
    .trim();
}

// ===== 翻译流水线 =====

// Common function words that do not have sign language equivalents
const FUNCTION_WORDS = new Set([
  "的",
  "了",
  "着",
  "过",
  "吧",
  "吗",
  "呢",
  "啊",
  "嘛",
  "呗",
  "哦",
  "嗯",
  "呀",
  "啦",
  "哈",
  "哇",
  "哎",
  "喂",
  "个",
]);

// Step 0: Remove function words before matching
function stripFunctionWords(text) {
  let result = "";
  for (let i = 0; i < text.length; i++) {
    if (!FUNCTION_WORDS.has(text[i])) result += text[i];
  }
  return result;
}

function findGesture(subtitleText) {
  const text = stripFunctionWords(normalizeText(subtitleText));
  if (!text) return null;

  // 第1层：多字词匹配（最长优先）
  const entries = Object.entries(SIGNS).sort(
    (a, b) => b[1].texts[0].length - a[1].texts[0].length,
  );
  for (const [id, sign] of entries) {
    for (const t of sign.texts) {
      if (text.includes(t)) {
        console.log("[SB] Sign match:", id, "→", t);
        return { frames: sign.frames, meta: sign.meta };
      }
    }
  }

  // 第2层：单字匹配
  const chars = text.replace(/\s/g, "");
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    if (SINGLE_CHARS[ch]) {
      console.log("[SB] Char match:", ch);
      return { frames: SINGLE_CHARS[ch] };
    }
  }

  // 第3层：默认（空闲姿态）
  console.log("[SB] No match, using idle");
  return { frames: [frm({}, 0.5)] };
}

// ===== 兼容旧版接口 =====
const GESTURES = buildLookup();
const CHARS = SINGLE_CHARS;

export {
  handShape,
  gesture,
  SIGNS,
  GESTURES,
  CHARS,
  addChar,
  findGesture,
  normalizeText,
};
