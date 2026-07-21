/**
 * SignBridge v15 — 修复骨骼映射 + 真实手语手势库
 * Godette模型: 227骨骼, Clavic/Arm/Hand 使用带点号的实际名称
 */
import * as THREE from './three.module.js';
import { GLTFLoader } from './jsm/loaders/GLTFLoader.js';

// Godette骨骼映射 — 使用GLB中的实际骨骼名称
const BONE_SHORT = {
  'Root_225':'root','Body_220':'body','Hip_218':'hip',
  'Spine_1_199':'spine','Spine_2_198':'chest','Ribcage_197':'upperChest',
  'Neck_1_132':'neck','Neck_2_131':'neck2','Neck_3_130':'neck3','Head_129':'head',
  'ClavicR_192':'rShoulder','Arm_Upper_1R_187':'rUpperArm','Arm_Lower_1R_185':'rForearm','HandR_184':'rHand',
  'ClavicL_162':'lShoulder','Arm_Upper_1L_157':'lUpperArm','Arm_Lower_1L_155':'lForearm','HandL_154':'lHand',
  'ThumbR_178':'rthumb','Finger_1R002_165':'rindex','Finger_2R002_168':'rmiddle','Finger_3R002_171':'rring','Finger_4R002_174':'rpinky',
  'ThumbL_148':'lthumb','Finger_1L002_135':'lindex','Finger_2L002_138':'lmiddle','Finger_3L002_141':'lring','Finger_4L002_144':'lpinky',
};

let renderer, scene, camera, skinnedMesh = null;
let boneMap = {};
let modelReady = false;

// 动画系统
let animQueue = [], animTimer = null, animPlaying = false;
function playFrames(frames) {
  if (!frames || frames.length === 0) return;
  stopAnimation();
  animQueue = [...frames];
  animPlaying = true;
  playNextFrame();
}
function playNextFrame() {
  if (!animPlaying || animQueue.length === 0) return;
  const f = animQueue.shift();
  const pose = f.value || f.rotation || f;
  applyPose(pose);
  animTimer = setTimeout(playNextFrame, (f.duration || 0.3) * 1000);
}
function stopAnimation() {
  animPlaying = false;
  if (animTimer) { clearTimeout(animTimer); animTimer = null; }
}

// 工具函数
function deg(x,y,z){ const d=Math.PI/180; return {x:(x||0)*d, y:(y||0)*d, z:(z||0)*d}; }
function frm(pose,dur){ return {value:pose, duration:dur||0.8}; }

const KEYS = ['lShoulder','lUpperArm','lForearm','lHand','rShoulder','rUpperArm','rForearm','rHand','head'];
function mkPose(parts){
  const p={};
  for(const k of KEYS) p[k]={x:0,y:0,z:0};
  if(parts) for(const k in parts) if(parts[k]) p[k]={x:parts[k].x||0,y:parts[k].y||0,z:parts[k].z||0};
  return p;
}

// ===== 手势构建函数 =====
// 右手姿势: 肩+上臂+前臂+手+5指
function rPose(shX,shY,shZ, uaX,uaY,uaZ, faX,faY,faZ, hX,hY,hZ, thX,ixX,mdX,rgX,pyX){
  const p = mkPose();
  p.rShoulder = deg(shX||0, shY||0, shZ||0);
  p.rUpperArm = deg(uaX||0, uaY||0, uaZ||0);
  p.rForearm = deg(faX||0, faY||0, faZ||0);
  p.rHand = deg(hX||0, hY||0, hZ||0);
  // 手指: z轴旋转弯曲
  if(thX!==undefined)p.rthumb=deg(0,0,thX);
  if(ixX!==undefined)p.rindex=deg(0,0,ixX);
  if(mdX!==undefined)p.rmiddle=deg(0,0,mdX);
  if(rgX!==undefined)p.rring=deg(0,0,rgX);
  if(pyX!==undefined)p.rpinky=deg(0,0,pyX);
  return p;
}

// 左手同理
function lPose(shX,shY,shZ, uaX,uaY,uaZ, faX,faY,faZ, hX,hY,hZ, thX,ixX,mdX,rgX,pyX){
  const p = mkPose();
  p.lShoulder = deg(shX||0, shY||0, shZ||0);
  p.lUpperArm = deg(uaX||0, uaY||0, uaZ||0);
  p.lForearm = deg(faX||0, faY||0, faZ||0);
  p.lHand = deg(hX||0, hY||0, hZ||0);
  if(thX!==undefined)p.lthumb=deg(0,0,thX);
  if(ixX!==undefined)p.lindex=deg(0,0,ixX);
  if(mdX!==undefined)p.lmiddle=deg(0,0,mdX);
  if(rgX!==undefined)p.lring=deg(0,0,rgX);
  if(pyX!==undefined)p.lpinky=deg(0,0,pyX);
  return p;
}

// ===== 中国手语 (CSL) 词库 =====
// 每个手势用帧序列表示: [{value:pose, duration:0.3}, ...]
// 手语动作: T-Pose下双臂自然下垂，需要先抬臂再做手势

// 你好: 右手在胸前，手掌朝外，四指并拢拇指自然张开，向前微动
const hello = rPose(
  0,0,0,          // 肩不动
  75,-10,-15,     // 上臂: 前抬75°(x), 稍内收(y), 稍内旋(z)
  -95,0,0,        // 前臂: 继续弯曲-95°向前
  0,0,15,         // 手: 稍外转15°
  0,0,0,0,0       // 五指自然
);
// 你好挥手版本
const helloWave = rPose(
  0,0,0,
  70,-10,-15,
  -90,0,0,
  0,0,20,
  0,0,0,0,0
);

// 谢谢: 右手拇指竖起，其余四指握拳，在胸前向前微点
const xiexie = rPose(
  0,0,0,
  75,-15,-10,
  -90,0,0,
  0,10,10,
  -80,  // 拇指竖起(z=-80°≈90度弯曲反方向)
  -80,  // 食指弯曲
  -80,  // 中指弯曲
  -80,  // 无名指弯曲
  -80   // 小指弯曲
);

// 欢迎: 双手同时做"请"的手势，手臂张开
const huanying_R = rPose(
  10,20,0,        // 肩稍外展
  40,10,0,        // 上臂抬起40°
  -60,5,0,        // 前臂内弯
  10,0,0,         // 手掌朝上
  -30,-30,-30,-30,-30  // 五指微弯
);
const huanying_L = lPose(
  10,-20,0,
  40,-10,0,
  -60,-5,0,
  10,0,0,
  -30,-30,-30,-30,-30
);

// 是/对: 右手食指中指并拢伸出，其余握拳，在胸前向下点
const yes = rPose(
  0,0,0,
  75,-10,-15,
  -95,0,0,
  -5,0,5,
  -80,    // 拇指向掌心弯
  -5,     // 食指伸出(微弯)
  -5,     // 中指伸出(微弯)
  -80,    // 无名指弯曲
  -80     // 小指弯曲
);

// 不/没有: 右手食指竖起，其余握拳，左右摆动一次
const bu = rPose(
  0,0,0,
  80,-10,-15,
  -95,0,0,
  10,0,5,
  -85,    // 拇指弯曲
  -5,     // 食指直伸
  -85,    // 中指弯曲
  -85,    // 无名指弯曲
  -85     // 小指弯曲
);

// 好: 右手拇指竖起，其余四指握拳
const hao = rPose(
  0,0,0,
  75,-10,-15,
  -90,0,0,
  5,5,5,
  -80,
  -80,
  -80,
  -80,
  -80
);

// 帮助: 右手掌摊开，托一下
const bangzhu = rPose(
  0,0,0,
  60,10,-10,
  -80,0,0,
  -10,5,0,
  20,20,20,20,20  // 五指张开
);

// 我: 右手食指指向自己胸口
const wo = rPose(
  0,0,0,
  50,-15,-15,
  -95,0,0,
  15,0,5,
  -80,-5,-80,-80,-80
);

// 你: 右手食指指向对方
const ni = rPose(
  0,0,0,
  80,-10,-15,
  -100,0,0,
  5,0,5,
  -80,-5,-80,-80,-80
);

// 爱: 右手抚摸心脏位置 (左手辅助托)
const ai_R = rPose(
  -10,15,5,
  40,0,-10,
  -70,0,0,
  -10,0,0,
  -60,-30,-30,-30,-30
);
const ai_L = lPose(
  -10,-15,5,
  40,0,-10,
  -70,0,0,
  -10,0,0,
  -60,-30,-30,-30,-30
);

// 再见: 右手五指张开，手掌朝外摆动
const zaijian = rPose(
  0,0,0,
  85,-10,-15,
  -90,0,0,
  5,0,20,
  -20,-20,-20,-20,-20
);
const zaijian_wave = rPose(
  0,0,0,
  85,-10,-15,
  -90,0,0,
  5,0,30,
  -20,-20,-20,-20,-20
);

// T-Pose 归零
const tpose = mkPose();

// ===== 构建动画序列 =====
const GESTURES = {
  // 您好 => 你 + 好
  '你好': [
    frm(ni, 0.6),
    frm(tpose, 0.15),
    frm(hao, 0.7),
  ],
  '您好': [
    frm(ni, 0.6),
    frm(tpose, 0.15),
    frm(hao, 0.7),
  ],
  '谢谢': [
    frm(xiexie, 0.8),
  ],
  '多谢': [
    frm(xiexie, 0.8),
  ],
  '欢迎': [
    frm({...huanying_R, ...huanying_L}, 0.8),
  ],
  '是': [
    frm(yes, 0.6),
  ],
  '对': [
    frm(yes, 0.6),
  ],
  '不': [
    frm(bu, 0.5),
  ],
  '好': [
    frm(hao, 0.7),
  ],
  '帮助': [
    frm(bangzhu, 0.7),
  ],
  '我': [
    frm(wo, 0.6),
  ],
  '你': [
    frm(ni, 0.6),
  ],
  '爱': [
    frm({...ai_R, ...ai_L}, 0.8),
  ],
  '再见': [
    frm(zaijian, 0.6),
    frm(zaijian_wave, 0.4),
    frm(zaijian, 0.4),
  ],
  '什么': [
    frm(tpose, 0.5),
  ],
  '为什么': [
    frm(tpose, 0.5),
  ],
  '喜欢': [
    frm({...ai_R, ...ai_L}, 0.7),
  ],
  '开心': [
    frm(rPose(0,0,0,80,-10,-15,-90,0,0,0,0,10,-20,-20,-20,-20,-20), 0.6),
  ],
  '真': [
    frm(yes, 0.5),
  ],
  '太': [
    frm(hao, 0.5),
  ],
};

// 单字词库 (fallback)
const CHARS = {};
function addChar(c, fs){CHARS[c]=fs;}
// 常见字的手语
addChar('你', [frm(ni, 0.6)]);
addChar('好', [frm(hao, 0.7)]);
addChar('谢', [frm(xiexie, 0.8)]);
addChar('欢', [frm({...huanying_R, ...huanying_L}, 0.6)]);
addChar('迎', [frm({...huanying_R, ...huanying_L}, 0.6)]);
addChar('帮', [frm(bangzhu, 0.6)]);
addChar('助', [frm(bangzhu, 0.6)]);
addChar('我', [frm(wo, 0.6)]);
addChar('爱', [frm({...ai_R, ...ai_L}, 0.8)]);
addChar('是', [frm(yes, 0.6)]);
addChar('对', [frm(yes, 0.6)]);
addChar('再', [frm(zaijian, 0.6)]);
addChar('见', [frm(zaijian, 0.6)]);
addChar('不', [frm(bu, 0.5)]);
addChar('喜', [frm({...ai_R, ...ai_L}, 0.7)]);
// 默认空手势
addChar(' ', [frm(tpose, 0.3)]);

function handPose(uX,uY,uZ, fX,fY,fZ, hX,hY,hZ){
  return mkPose({
    rUpperArm:deg(uX||0,uY||0,uZ||0),
    rForearm:deg(fX||0,fY||0,fZ||0),
    rHand:deg(hX||0,hY||0,hZ||0),
  });
}

function textToAnimation(text){
  const t = text.trim(); if (!t) return false;
  // 最长匹配优先
  const entries = Object.entries(GESTURES).sort((a,b)=>b[0].length-a[0].length);
  for (const [word, frames] of entries){
    if (t.includes(word)){
      console.log('[SB] Gesture:', word);
      playFrames(frames);
      return true;
    }
  }
  // 单字匹配
  for (let i = 0; i < t.length; i++){
    if (CHARS[t[i]]){
      console.log('[SB] Char:', t[i]);
      playFrames(CHARS[t[i]]);
      return true;
    }
  }
  // 默认
  console.log('[SB] Default gesture');
  playFrames([frm(mkPose(), 0.5)]);
  return true;
}

let REST = {};

function applyPose(pose){
  if(!pose||!skinnedMesh?.skeleton)return;
  // 1. Reset all to REST
  for(const k in boneMap){
    const r=REST[k]; if(!r)continue;
    boneMap[k].rotation.set(r.x, r.y, r.z);
  }
  // 2. Apply delta
  for(const name in pose){
    if(!Object.prototype.hasOwnProperty.call(pose,name))continue;
    const rot=pose[name]; if(!rot||typeof rot.x==='undefined')continue;
    const bone=boneMap[name];
    if(bone){
      const r=REST[name]||{x:0,y:0,z:0};
      bone.rotation.set(r.x+(rot.x||0), r.y+(rot.y||0), r.z+(rot.z||0));
    }
  }
  skinnedMesh.skeleton.update();
}

let _animId = 0;
function animate(){
  _animId = requestAnimationFrame(animate);
  try {
    if (scene) scene.updateMatrixWorld(true);
    if (renderer && scene && camera) renderer.render(scene, camera);
  } catch(e){}
}

function notify(type, data){
  try { parent.postMessage({source:'signbridge-iframe', type, ...(data||{})}, '*'); } catch(e){}
}

// ===== 初始化 =====
function init(modelUrl){
  console.log('[SB] Loading:', modelUrl);
  const container = document.getElementById('c');
  if (!container) return;

  renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setClearColor(0x000000, 0);  // 透明背景
  container.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xdce8f5);

  scene.add(new THREE.AmbientLight(0xffffff, 1.2));
  const dl = new THREE.DirectionalLight(0xffffff, 1.0); dl.position.set(2, 5, 3); scene.add(dl);
  const dl2 = new THREE.DirectionalLight(0xffffff, 0.6); dl2.position.set(-1, 2, -1); scene.add(dl2);

  camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 100);
  camera.position.set(0, 0.65, 1.5);
  camera.lookAt(0, 0.5, 0);

  const loader = new GLTFLoader();
  loader.load(
    modelUrl,
    (gltf) => {
      console.log('[SB] Model loaded');
      skinnedMesh = null;
      boneMap = {};

      gltf.scene.traverse((child) => {
        if (child.isSkinnedMesh && !skinnedMesh) {
          skinnedMesh = child;
          console.log('[SB] Mesh:', child.name, 'tri:', child.geometry?.index?.count || '?');
        }
      });

      if (skinnedMesh?.skeleton) {
        const bones = skinnedMesh.skeleton.bones;
        console.log('[SB] Bones:', bones.length);

        for (const b of bones) {
          // 精确匹配
          if (BONE_SHORT[b.name]) {
            boneMap[BONE_SHORT[b.name]] = b;
          }
        }

        const crit = ['rUpperArm','rForearm','rHand','lUpperArm','lForearm','lHand','head'];
        const st = {};
        for (const k of crit) st[k] = !!boneMap[k];
        console.log('[SB] BoneMap status:', JSON.stringify(st));

        if (!boneMap.rUpperArm) {
          console.warn('[SB] ⚠ rUpperArm not mapped! Available bones:', bones.map(b=>b.name).filter(n=>n.includes('Arm')||n.includes('Hand')||n.includes('Clavic')));
        }
      }

      scene.add(gltf.scene);
      gltf.scene.scale.set(1.093,1.093,1.093);
      gltf.scene.position.y = -0.8;
      window._sbModel = gltf.scene;

      // Save REST rotations
      REST = {};
      for(const k in boneMap) REST[k] = {x:boneMap[k].rotation.x, y:boneMap[k].rotation.y, z:boneMap[k].rotation.z};
      console.log('[SB] REST (A-Pose) saved for', Object.keys(REST).length, 'bones');
      
      modelReady = true;
      createControls();
      createDebugPanel();
      notify('READY', {});
      console.log('[SB] ✅ Ready');
    },
    undefined,
    (err) => {
      console.error('[SB] Load error:', err);
      notify('ERROR', { message: err.message || String(err) });
    }
  );

  animate();
}

// ===== 模型中控按钮 =====
function createControls(){
  const el = document.getElementById('c'); if(!el)return;
  const ctrl = document.createElement('div');
  ctrl.id = 'sb-3d-ctrl';
  ctrl.style.cssText = 'position:absolute;bottom:4px;left:50%;transform:translateX(-50%);display:flex;gap:2px;z-index:20;';
  
  let bgIdx = 0;
  const bgColors = [0xdce8f5, null, 0x1a1a2e, 0x2d2d2d, 0xffffff, 0xe8f0e8, 0xf0e8e0];
  
  const btns = [
    { icon:'▲', fn(){ if(window._sbModel) window._sbModel.position.y += 0.06; } },
    { icon:'▼', fn(){ if(window._sbModel) window._sbModel.position.y -= 0.06; } },
    { icon:'◀', fn(){ if(window._sbModel) window._sbModel.rotation.y += 0.3; } },
    { icon:'▶', fn(){ if(window._sbModel) window._sbModel.rotation.y -= 0.3; } },
    { icon:'+', fn(){ const s=Math.min((window._sbModel?.scale?.x||1)*1.12, 2.5); if(window._sbModel) window._sbModel.scale.set(s,s,s); } },
    { icon:'−', fn(){ const s=Math.max((window._sbModel?.scale?.x||1)*0.88, 0.2); if(window._sbModel) window._sbModel.scale.set(s,s,s); } },
    { icon:'🎨', fn(){ bgIdx=(bgIdx+1)%bgColors.length; if(scene) scene.background = bgColors[bgIdx] ? new THREE.Color(bgColors[bgIdx]) : null; } },
  ];

  btns.forEach(b=>{
    const btn = document.createElement('button');
    btn.textContent = b.icon;
    btn.style.cssText = 'width:24px;height:24px;border:none;border-radius:4px;background:rgba(0,0,0,0.55);color:#fff;cursor:pointer;font-size:11px;display:flex;align-items:center;justify-content:center;';
    btn.addEventListener('click', e=>{ e.stopPropagation(); b.fn(); });
    ctrl.appendChild(btn);
  });
  el.appendChild(ctrl);
}

// ===== 调参面板 =====
function createDebugPanel(){
  const el = document.getElementById('c'); if(!el)return;
  
  const toggleBtn = document.createElement('button');
  toggleBtn.textContent = '🔧';
  toggleBtn.title = '骨骼调参';
  toggleBtn.style.cssText = 'position:absolute;top:4px;left:4px;width:28px;height:28px;border:none;border-radius:4px;background:rgba(0,0,0,0.65);color:#ff0;cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:center;z-index:31;';
  
  const panel = document.createElement('div');
  panel.id = 'sb-debug';
  panel.style.cssText = 'position:absolute;top:32px;left:4px;width:260px;max-height:80%;overflow-y:auto;background:rgba(0,0,0,0.88);color:#0f0;font-size:10px;font-family:monospace;padding:6px;border-radius:6px;z-index:30;display:none;';
  
  toggleBtn.onclick = (e)=>{ e.stopPropagation(); panel.style.display = panel.style.display==='none'?'block':'none'; };
  el.appendChild(toggleBtn);

  const bones = [
    {name:'rUpperArm', label:'右上臂', keys:['x','y','z']},
    {name:'rForearm', label:'右前臂', keys:['x','y','z']},
    {name:'rHand', label:'右手', keys:['x','y','z']},
    {name:'rShoulder', label:'右肩', keys:['x','y','z']},
    {name:'lUpperArm', label:'左上臂', keys:['x','y','z']},
    {name:'lForearm', label:'左前臂', keys:['x','y','z']},
    {name:'lHand', label:'左手', keys:['x','y','z']},
    {name:'lShoulder', label:'左肩', keys:['x','y','z']},
    {name:'head', label:'头', keys:['x','y','z']},
    {name:'rthumb', label:'右拇指', keys:['z']},
    {name:'rindex', label:'右食指', keys:['z']},
    {name:'rmiddle', label:'右中指', keys:['z']},
    {name:'rring', label:'右无名指', keys:['z']},
    {name:'rpinky', label:'右小指', keys:['z']},
  ];

  let html = '<div style="margin-bottom:4px;font-weight:bold;color:#ff0;">骨骼调参 (弧度)</div>';
  
  bones.forEach(b => {
    html += '<div style="margin:2px 0;padding:2px;border:1px solid #333;border-radius:2px;">';
    html += '<div style="color:#ff0;margin-bottom:1px;">'+b.label+'</div>';
    const bm = boneMap[b.name];
    if(!bm){
      html += '<span style="color:#f00;">未映射</span>';
    } else {
      b.keys.forEach(k => {
        const id = 'dbg_'+b.name+'_'+k;
        const val = bm.rotation[k] || 0;
        html += k+': <input id="'+id+'" type="range" min="-3.2" max="3.2" step="0.01" value="'+val+'" oninput="window._dbgSet(\''+b.name+'\',\''+k+'\',this.value)" style="width:45px;vertical-align:middle;">';
        html += '<span id="'+id+'_v" style="display:inline-block;width:32px;text-align:right;">'+val.toFixed(2)+'</span> ';
      });
    }
    html += '</div>';
  });
  
  html += '<button onclick="window._dbgExport()" style="margin-top:6px;width:100%;padding:4px;background:#393;color:#fff;border:none;border-radius:3px;cursor:pointer;">📋 导出姿势</button>';
  html += '<button onclick="window._dbgReset()" style="margin-top:2px;width:100%;padding:4px;background:#933;color:#fff;border:none;border-radius:3px;cursor:pointer;">🔄 重置全部</button>';
  html += '<pre id="dbg-out" style="margin-top:4px;color:#ff0;font-size:9px;white-space:pre-wrap;word-break:break-all;max-height:80px;overflow-y:auto;"></pre>';
  
  panel.innerHTML = html;
  el.appendChild(panel);

  window._dbgSet = function(boneName, key, valStr){
    const b = boneMap[boneName]; if(!b)return;
    const val = parseFloat(valStr);
    b.rotation[key] = val;
    if(skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
    const vEl = document.getElementById('dbg_'+boneName+'_'+key+'_v');
    if(vEl) vEl.textContent = val.toFixed(2);
  };

  window._dbgExport = function(){
    const lines = [];
    for(const b of bones){
      const bm = boneMap[b.name]; if(!bm)continue;
      const rots = b.keys.map(k => bm.rotation[k].toFixed(2)).join(', ');
      lines.push(b.name + ': deg('+rots+')');
    }
    const text = lines.join(',\\n');
    document.getElementById('dbg-out').textContent = text;
    navigator.clipboard.writeText(text).catch(()=>{});
    console.log('[SB] Exported:\\n' + text);
  };

  window._dbgReset = function(){
    for(const k in boneMap){
      const r = REST[k] || {x:0,y:0,z:0};
      boneMap[k].rotation.set(r.x, r.y, r.z);
    }
    for(const k in boneMap) boneMap[k].rotation.set(0,0,0);
    if(skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
    for(const b of bones){
      const bm = boneMap[b.name]; if(!bm)continue;
      for(const k of b.keys){
        const inp = document.getElementById('dbg_'+b.name+'_'+k);
        const sp = document.getElementById('dbg_'+b.name+'_'+k+'_v');
        if(inp) inp.value = '0';
        if(sp) sp.textContent = '0.00';
      }
    }
  };
}

// ===== 消息处理 =====
notify('LOADED', {});
window.addEventListener('message', ev => {
  if (!ev.data || ev.data.source !== 'signbridge-page') return;
  console.log('[SB] iframe rx:', ev.data.type, ev.data.text||'');
  switch(ev.data.type){
    case 'INIT': init(ev.data.modelUrl); break;
    case 'SUBTITLE_TEXT': if(modelReady && ev.data.text) textToAnimation(ev.data.text); break;
    case 'RESIZE': if(renderer){ renderer.setSize(ev.data.width, ev.data.height); camera.aspect = ev.data.width/ev.data.height; camera.updateProjectionMatrix(); } break;
  }
});
console.log('[SB] v15 — fixed bone mapping + CSL gestures');
