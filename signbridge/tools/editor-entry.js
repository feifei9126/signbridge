import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const D = Math.PI / 180;

const BONE_SHORT = {
  'mixamorig6Hips':'hip', 'mixamorig6Spine':'spine', 'mixamorig6Spine1':'spine1', 'mixamorig6Spine2':'spine2',
  'mixamorig6Neck':'neck', 'mixamorig6Head':'head',
  'mixamorig6RightShoulder':'rShoulder', 'mixamorig6RightArm':'rUpperArm',
  'mixamorig6RightForeArm':'rForearm', 'mixamorig6RightHand':'rHand',
  'mixamorig6RightHandThumb1':'rthumb1', 'RightHandThumb2':'rthumb2', 'RightHandThumb3':'rthumb3', 'RightHandThumb4':'rthumb4',
  'mixamorig6RightHandIndex1':'rindex1', 'mixamorig6RightHandIndex2':'rindex2', 'mixamorig6RightHandIndex3':'rindex3', 'mixamorig6RightHandIndex4':'rindex4',
  'mixamorig6RightHandMiddle1':'rmiddle1', 'mixamorig6RightHandMiddle2':'rmiddle2', 'mixamorig6RightHandMiddle3':'rmiddle3', 'mixamorig6RightHandMiddle4':'rmiddle4',
  'mixamorig6RightHandRing1':'rring1', 'mixamorig6RightHandRing2':'rring2', 'mixamorig6RightHandRing3':'rring3', 'mixamorig6RightHandRing4':'rring4',
  'mixamorig6RightHandPinky1':'rpinky1', 'mixamorig6RightHandPinky2':'rpinky2', 'mixamorig6RightHandPinky3':'rpinky3', 'mixamorig6RightHandPinky4':'rpinky4',
  'mixamorig6LeftShoulder':'lShoulder', 'mixamorig6LeftArm':'lUpperArm',
  'mixamorig6LeftForeArm':'lForearm', 'mixamorig6LeftHand':'lHand',
  'mixamorig6LeftHandThumb1':'lthumb1', 'LeftHandThumb2':'lthumb2', 'LeftHandThumb3':'lthumb3', 'LeftHandThumb4':'lthumb4',
  'mixamorig6LeftHandIndex1':'lindex1', 'mixamorig6LeftHandIndex2':'lindex2', 'mixamorig6LeftHandIndex3':'lindex3', 'mixamorig6LeftHandIndex4':'lindex4',
  'mixamorig6LeftHandMiddle1':'lmiddle1', 'mixamorig6LeftHandMiddle2':'lmiddle2', 'mixamorig6LeftHandMiddle3':'lmiddle3', 'mixamorig6LeftHandMiddle4':'lmiddle4',
  'mixamorig6LeftHandRing1':'lring1', 'mixamorig6LeftHandRing2':'lring2', 'mixamorig6LeftHandRing3':'lring3', 'mixamorig6LeftHandRing4':'lring4',
  'mixamorig6LeftHandPinky1':'lpinky1', 'mixamorig6LeftHandPinky2':'lpinky2', 'mixamorig6LeftHandPinky3':'lpinky3', 'mixamorig6LeftHandPinky4':'lpinky4',
};

const EDIT_BONES = [
  { name:'head', label:'头', keys:['x','y','z'] },
  { name:'rShoulder', label:'右肩', keys:['x','y','z'], mirror:'lShoulder' },
  { name:'rUpperArm', label:'右上臂', keys:['x','y','z'], mirror:'lUpperArm' },
  { name:'rForearm', label:'右前臂', keys:['x','y','z'], mirror:'lForearm' },
  { name:'rHand', label:'右手', keys:['x','y','z'], mirror:'lHand' },
  { name:'lShoulder', label:'左肩', keys:['x','y','z'] },
  { name:'lUpperArm', label:'左上臂', keys:['x','y','z'] },
  { name:'lForearm', label:'左前臂', keys:['x','y','z'] },
  { name:'lHand', label:'左手', keys:['x','y','z'] },
  { name:'rthumb1', label:'右拇指1', keys:['x'], mirror:'lthumb1' },
  { name:'rindex1', label:'右食指1', keys:['x'], mirror:'lindex1' },
  { name:'rmiddle1', label:'右中指1', keys:['x'], mirror:'lmiddle1' },
  { name:'rring1', label:'右无名指1', keys:['x'], mirror:'lring1' },
  { name:'rpinky1', label:'右小指1', keys:['x'], mirror:'lpinky1' },
  { name:'lthumb1', label:'左拇指1', keys:['x'] },
  { name:'lindex1', label:'左食指1', keys:['x'] },
  { name:'lmiddle1', label:'左中指1', keys:['x'] },
  { name:'lring1', label:'左无名指1', keys:['x'] },
  { name:'lpinky1', label:'左小指1', keys:['x'] },
];
const MIRROR_MAP = {};
EDIT_BONES.forEach(b => { if (b.mirror) MIRROR_MAP[b.name] = b.mirror; });

// --- Three.js ---
const container = document.getElementById('viewer');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xdce8f5);

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
camera.position.set(1.2, 0.8, 2.2);
camera.lookAt(0, 0.7, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
container.appendChild(renderer.domElement);

const ctrl = new OrbitControls(camera, renderer.domElement);
ctrl.target.set(0, 0.7, 0);
ctrl.enableDamping = true; ctrl.dampingFactor = 0.08;
ctrl.update();

scene.add(new THREE.AmbientLight(0xffffff, 1.2));
const l1 = new THREE.DirectionalLight(0xffffff, 1.5); l1.position.set(2,4,3); scene.add(l1);
const l2 = new THREE.DirectionalLight(0x8888ff, 0.6); l2.position.set(-2,1,-1); scene.add(l2);
const grid = new THREE.GridHelper(3, 20, 0xcccccc, 0xdddddd); grid.position.y = -0.5; scene.add(grid);

let skinnedMesh = null, modelRoot = null;
const boneMap = {};
let animTimer = null, animFrames = [], animIdx = 0, _lastTime = 0;

function resize() {
  const w = container.clientWidth, h = container.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
function anim() {
  requestAnimationFrame(anim);
  ctrl.update();
  renderer.render(scene, camera);
  const now = performance.now();
  document.getElementById('status-bar').textContent = '骨骼: '+Object.keys(boneMap).length+' | FPS: '+(1000/(now-_lastTime||16)).toFixed(0);
  _lastTime = now;
}

async function loadModel() {
  const loader = new GLTFLoader();
  try {
    const gltf = await loader.loadAsync('./model.glb');
    modelRoot = gltf.scene;
    scene.add(modelRoot);
    modelRoot.traverse(obj => { if (obj.isSkinnedMesh && !skinnedMesh) skinnedMesh = obj; });
    modelRoot.traverse(obj => {
      if (obj.isBone) {
        const n = obj.name;
        if (BONE_SHORT[n]) boneMap[BONE_SHORT[n]] = obj;
        const c = n.replace(/^mixamorig6/, '');
        if (c !== n && BONE_SHORT[c]) boneMap[BONE_SHORT[c]] = obj;
      }
    });
    modelRoot.position.set(0, -0.15, 0);
    modelRoot.scale.set(0.85, 0.85, 0.85);
    console.log('[PE] Loaded, bones:', Object.keys(boneMap).length);
    document.getElementById('pose-label').textContent = '就绪 - 选预设或拖滑块';
    buildSliders();
    resetAll();
  } catch (err) {
    console.error('[PE] Load failed:', err);
    document.getElementById('pose-label').textContent = '加载失败: ' + err.message;
  }
}

function syncSliders() {
  EDIT_BONES.forEach(b => {
    const bm = boneMap[b.name]; if (!bm) return;
    b.keys.forEach(k => {
      const s = document.getElementById('sl_'+b.name+'_'+k);
      const v = document.getElementById('sl_'+b.name+'_'+k+'_v');
      const val = bm.rotation[k] || 0;
      if (s) s.value = val;
      if (v) v.textContent = val.toFixed(2);
    });
  });
}

function applyPoseObj(pose) {
  for (const name in pose) {
    const b = boneMap[name]; if (!b) continue;
    const rot = pose[name];
    if (rot && 'x' in rot) b.rotation.set(rot.x||0, rot.y||0, rot.z||0);
  }
  if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
  syncSliders();
}

function getCurrentPose() {
  const p = {};
  for (const k in boneMap) p[k] = { x: boneMap[k].rotation.x, y: boneMap[k].rotation.y, z: boneMap[k].rotation.z };
  return p;
}

let toastT;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent=msg; el.classList.add('show');
  if(toastT)clearTimeout(toastT);
  toastT=setTimeout(()=>el.classList.remove('show'),2000);
}

// ==== 全PUBLIC API ====
const API = {};
window.__PE = API;

API.resetAll = function() {
  for (const k in boneMap) boneMap[k].rotation.set(0,0,0);
  if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
  syncSliders();
  document.getElementById('pose-label').textContent = 'T-Pose';
};

API.exportPose = function() {
  const json = JSON.stringify(getCurrentPose(), null, 2);
  document.getElementById('output-text').textContent = json;
  navigator.clipboard.writeText(json).then(() => toast('JSON 已复制'));
};

API.exportAsCode = function() {
  const pose = getCurrentPose();
  const lines = [];
  for (const b of EDIT_BONES) {
    if (!boneMap[b.name]) continue;
    const bm = boneMap[b.name];
    const vals = b.keys.map(k => ((bm.rotation[k]||0)/D).toFixed(1));
    if (vals.every(v => parseFloat(v)===0)) continue;
    lines.push('  '+b.name+': deg('+vals.join(', ')+'),');
  }
  const code = 'const pose = makePose({\n' + lines.join('\n') + '\n});';
  document.getElementById('output-text').textContent = code;
  navigator.clipboard.writeText(code).then(() => toast('代码已复制'));
};

API.importPose = function() {
  const text = prompt('粘贴 JSON 姿势数据:');
  if (!text) return;
  try { applyPoseObj(JSON.parse(text)); document.getElementById('pose-label').textContent='导入的姿势'; toast('已导入'); }
  catch(e) { toast('JSON 错误: '+e.message); }
};

const PRESETS = {
  tpose: () => { for(const k in boneMap)boneMap[k].rotation.set(0,0,0); if(skinnedMesh?.skeleton)skinnedMesh.skeleton.update(); syncSliders(); },
  idle: () => applyPoseObj({ lUpperArm:{x:-5*D,y:5*D,z:0}, rUpperArm:{x:-5*D,y:-5*D,z:0}, lForearm:{x:-10*D,y:0,z:0}, rForearm:{x:-10*D,y:0,z:0} }),
  hello: () => applyPoseObj({ rShoulder:{x:0,y:0,z:-5*D}, rUpperArm:{x:35*D,y:10*D,z:0}, rForearm:{x:-60*D,y:5*D,z:-10*D}, rHand:{x:10*D,y:0,z:5*D} }),
  thanks: () => applyPoseObj({ rShoulder:{x:0,y:5*D,z:-5*D}, rUpperArm:{x:25*D,y:15*D,z:0}, rForearm:{x:-50*D,y:5*D,z:-10*D}, rHand:{x:0,y:10*D,z:-15*D}, head:{x:8*D,y:0,z:0} }),
  welcome: () => applyPoseObj({ rUpperArm:{x:30*D,y:20*D,z:0}, rForearm:{x:-60*D,y:-5*D,z:25*D}, lUpperArm:{x:30*D,y:-20*D,z:0}, lForearm:{x:-60*D,y:5*D,z:-25*D} }),
  yes: () => applyPoseObj({ rUpperArm:{x:20*D,y:5*D,z:0}, rForearm:{x:-45*D,y:0,z:5*D}, rHand:{x:0,y:-15*D,z:-5*D} }),
  no: () => applyPoseObj({ head:{x:-10*D,y:0,z:0}, rUpperArm:{x:20*D,y:10*D,z:0}, rForearm:{x:-40*D,y:0,z:10*D}, rHand:{x:0,y:-15*D,z:0} }),
  ok: () => applyPoseObj({ rShoulder:{x:0,y:0,z:-5*D}, rUpperArm:{x:30*D,y:15*D,z:0}, rForearm:{x:-55*D,y:5*D,z:-10*D}, rHand:{x:10*D,y:-5*D,z:15*D}, rthumb1:{x:20*D}, rindex1:{x:30*D}, rmiddle1:{x:40*D}, lthumb1:{x:20*D}, lindex1:{x:30*D}, lmiddle1:{x:40*D} }),
  help: () => applyPoseObj({ rUpperArm:{x:50*D,y:25*D,z:0}, rForearm:{x:-75*D,y:15*D,z:20*D}, lUpperArm:{x:40*D,y:-20*D,z:0}, lForearm:{x:-60*D,y:-10*D,z:15*D} }),
  point_r: () => applyPoseObj({ rUpperArm:{x:35*D,y:10*D,z:0}, rForearm:{x:-55*D,y:0,z:0}, rHand:{x:0,y:0,z:0}, rindex1:{x:0}, rmiddle1:{x:40*D}, rring1:{x:50*D}, rpinky1:{x:60*D} }),
  fist_r: () => applyPoseObj({ rthumb1:{x:40*D}, rindex1:{x:70*D}, rmiddle1:{x:70*D}, rring1:{x:70*D}, rpinky1:{x:70*D} }),
  open_r: () => applyPoseObj({ rthumb1:{x:0}, rindex1:{x:0}, rmiddle1:{x:0}, rring1:{x:0}, rpinky1:{x:0} }),
};

API.loadPreset = function(name) {
  if (PRESETS[name]) {
    PRESETS[name]();
    document.getElementById('pose-label').textContent = document.getElementById('preset-dd').selectedOptions[0].text;
  }
};

API.playSequence = function() {
  const sel = document.getElementById('preset-dd').value;
  if (sel === 'hello') {
    animFrames = [
      { pose:{rShoulder:{x:0,y:0,z:-5*D},rUpperArm:{x:35*D,y:10*D,z:0},rForearm:{x:-60*D,y:5*D,z:-10*D},rHand:{x:10*D,y:0,z:5*D}}, dur:0.4 },
      { pose:{rShoulder:{x:0,y:0,z:-5*D},rUpperArm:{x:40*D,y:15*D,z:0},rForearm:{x:-65*D,y:10*D,z:-5*D},rHand:{x:12*D,y:5*D,z:10*D}}, dur:0.4 },
      { pose:{rShoulder:{x:0,y:0,z:-5*D},rUpperArm:{x:35*D,y:10*D,z:0},rForearm:{x:-60*D,y:5*D,z:-10*D},rHand:{x:10*D,y:0,z:5*D}}, dur:0.4 },
    ];
  } else {
    animFrames = [{ pose:getCurrentPose(), dur:0.5 }, { pose:{}, dur:0.3 }];
  }
  animIdx = 0; playNextFrame();
  document.getElementById('pose-label').textContent = '播放中...';
};

function playNextFrame() {
  if (animIdx >= animFrames.length) { document.getElementById('pose-label').textContent='播放完成'; return; }
  applyPoseObj(animFrames[animIdx].pose||{});
  animIdx++;
  animTimer = setTimeout(playNextFrame, (animFrames[animIdx-1]?.dur||0.3)*1000);
}

API.stopSequence = function() {
  if(animTimer)clearTimeout(animTimer);
  animFrames=[]; animIdx=0;
  document.getElementById('pose-label').textContent='已停止';
};

API.onSymToggle = function() {
  toast(document.getElementById('sym-mode').checked ? '对称模式开' : '对称模式关');
};

// 绑定 onSlider 到 slider-input 的 oninput
window.onSlider = function(boneName, key, valStr) {
  const val = parseFloat(valStr);
  const b = boneMap[boneName]; if (!b) return;
  b.rotation[key] = val;
  if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
  const vEl = document.getElementById('sl_'+boneName+'_'+key+'_v');
  if (vEl) vEl.textContent = val.toFixed(2);
  if (document.getElementById('sym-mode')?.checked && MIRROR_MAP[boneName]) {
    const mName = MIRROR_MAP[boneName], mb = boneMap[mName];
    if (!mb) return;
    const mVal = (key === 'y') ? -val : val;
    mb.rotation[key] = mVal;
    if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
    const ms = document.getElementById('sl_'+mName+'_'+key);
    const mv = document.getElementById('sl_'+mName+'_'+key+'_v');
    if (ms) ms.value = mVal;
    if (mv) mv.textContent = mVal.toFixed(2);
  }
};

function buildSliders() {
  const scroll = document.getElementById('bones-scroll');
  let html = '';
  EDIT_BONES.forEach(b => {
    const bm = boneMap[b.name];
    if (!bm) { html += '<div class="bone-group"><div class="bone-label">'+b.label+' <span style="color:#f00">未映射</span></div></div>'; return; }
    html += '<div class="bone-group"><div class="bone-label">'+b.label+' ('+b.name+')</div>';
    b.keys.forEach(k => {
      const id = 'sl_'+b.name+'_'+k;
      const val = bm.rotation[k] || 0;
      html += '<div class="slider-row"><span class="axis">'+k+'</span>'+
        '<input type="range" id="'+id+'" min="-3.2" max="3.2" step="0.01" value="'+val+'" oninput="onSlider(\''+b.name+'\',\''+k+'\',this.value)">'+
        '<span class="val" id="'+id+'_v">'+val.toFixed(2)+'</span></div>';
    });
    html += '</div>';
  });
  scroll.innerHTML = html;
}

window.addEventListener('resize', resize);
resize(); anim(); loadModel();
