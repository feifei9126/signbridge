import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const D = Math.PI / 180;
function dg(x,y,z){ return {x:(x||0)*D, y:(y||0)*D, z:(z||0)*D}; }

const BONE_SHORT = {
  'Root_225':'root','Hip_218':'hip',
  'Spine_1_199':'spine','Spine_2_198':'chest','Ribcage_197':'ribcage',
  'Neck_1_132':'neck','Neck_2_131':'neck2','Neck_3_130':'neck3','Head_129':'head',
  'ClavicR_192':'rShoulder','Arm_Upper_1R_187':'rUpperArm','Arm_Lower_1R_185':'rForearm','HandR_184':'rHand',
  'ClavicL_162':'lShoulder','Arm_Upper_1L_157':'lUpperArm','Arm_Lower_1L_155':'lForearm','HandL_154':'lHand',
  'ThumbR_178':'rthumb','Finger_1R002_165':'rindex','Finger_2R002_168':'rmiddle','Finger_3R002_171':'rring','Finger_4R002_174':'rpinky',
  'ThumbL_148':'lthumb','Finger_1L002_135':'lindex','Finger_2L002_138':'lmiddle','Finger_3L002_141':'lring','Finger_4L002_144':'lpinky',
};

const EDIT_BONES = [
  {name:'head',label:'头',keys:['x','y','z']},
  {name:'rShoulder',label:'右肩',keys:['x','y','z'],mirror:'lShoulder'},
  {name:'rUpperArm',label:'右上臂',keys:['x','y','z'],mirror:'lUpperArm'},
  {name:'rForearm',label:'右前臂',keys:['x','y','z'],mirror:'lForearm'},
  {name:'rHand',label:'右手',keys:['x','y','z'],mirror:'lHand'},
  {name:'rthumb',label:'右拇指',keys:['x','y','z'],mirror:'lthumb'},
  {name:'rindex',label:'右食指',keys:['x','y','z'],mirror:'lindex'},
  {name:'rmiddle',label:'右中指',keys:['x','y','z'],mirror:'lmiddle'},
  {name:'rring',label:'右无名指',keys:['x','y','z'],mirror:'lring'},
  {name:'rpinky',label:'右小指',keys:['x','y','z'],mirror:'lpinky'},
  {name:'lShoulder',label:'左肩',keys:['x','y','z']},
  {name:'lUpperArm',label:'左上臂',keys:['x','y','z']},
  {name:'lForearm',label:'左前臂',keys:['x','y','z']},
  {name:'lHand',label:'左手',keys:['x','y','z']},
  {name:'lthumb',label:'左拇指',keys:['x','y','z']},
  {name:'lindex',label:'左食指',keys:['x','y','z']},
  {name:'lmiddle',label:'左中指',keys:['x','y','z']},
  {name:'lring',label:'左无名指',keys:['x','y','z']},
  {name:'lpinky',label:'左小指',keys:['x','y','z']},
];
const MIRROR_MAP = {};
EDIT_BONES.forEach(b=>{if(b.mirror)MIRROR_MAP[b.name]=b.mirror});

const container = document.getElementById('viewer');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xdce8f5);
const camera = new THREE.PerspectiveCamera(45,1,0.1,100);
camera.position.set(0, 1.2, 1.8); camera.lookAt(0,0.8,0);
const renderer = new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
container.appendChild(renderer.domElement);
const ctrl = new OrbitControls(camera,renderer.domElement);
ctrl.target.set(0,0.8,0); ctrl.enableDamping=true; ctrl.dampingFactor=0.08; ctrl.update();
scene.add(new THREE.AmbientLight(0xffffff,1.2));
const l1=new THREE.DirectionalLight(0xffffff,1.5); l1.position.set(2,4,3); scene.add(l1);
const l2=new THREE.DirectionalLight(0x8888ff,0.6); l2.position.set(-2,1,-1); scene.add(l2);

let skinnedMesh=null,modelRoot=null, boneMap={}, REST={};
let animTimer=null,animFrames=[],animIdx=0,_lt=0;

function resize(){const w=container.clientWidth,h=container.clientHeight;if(!w||!h)return;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix()}
function anim(){requestAnimationFrame(anim);ctrl.update();renderer.render(scene,camera);const n=performance.now();document.getElementById('status-bar').textContent='骨骼:'+Object.keys(boneMap).length+' FPS:'+(1000/(n-_lt||16)).toFixed(0);_lt=n}

async function loadModel(){
  const loader=new GLTFLoader();
  const resp=await fetch('./model.glb');
  if(!resp.ok)throw new Error('model.glb HTTP '+resp.status);
  const buf=await resp.arrayBuffer();
  return new Promise((resolve,reject)=>{loader.parse(buf,'',resolve,reject)});
}

function mapBones(gltf){
  boneMap={}; REST={};
  gltf.scene.traverse(child=>{if(child.isSkinnedMesh&&!skinnedMesh)skinnedMesh=child});
  if(skinnedMesh?.skeleton){
    const bones=skinnedMesh.skeleton.bones;
    for(const b of bones){
      if(BONE_SHORT[b.name]) {
        boneMap[BONE_SHORT[b.name]]=b;
        REST[BONE_SHORT[b.name]] = {x:b.rotation.x, y:b.rotation.y, z:b.rotation.z};
      }
    }
  }
}

function handleSliderInput(e){
  const bn=e.target.dataset.bone, k=e.target.dataset.key, v=parseFloat(e.target.value);
  const b=boneMap[bn]; if(!b)return;
  b.rotation[k]=v; if(skinnedMesh?.skeleton)skinnedMesh.skeleton.update();
  const ve=document.getElementById('sl_'+bn+'_'+k+'_v'); if(ve)ve.textContent=v.toFixed(2);
  if(document.getElementById('sym-mode')?.checked&&MIRROR_MAP[bn]){
    const mn=MIRROR_MAP[bn],mb=boneMap[mn]; if(!mb)return;
    const mv=(k==='y')?-v:v; mb.rotation[k]=mv; if(skinnedMesh?.skeleton)skinnedMesh.skeleton.update();
    const ms=document.getElementById('sl_'+mn+'_'+k),mv2=document.getElementById('sl_'+mn+'_'+k+'_v');
    if(ms)ms.value=mv; if(mv2)mv2.textContent=mv.toFixed(2);
  }
}

function buildSliders(){
  const scroll=document.getElementById('bones-scroll');
  let html='';
  EDIT_BONES.forEach(b=>{
    const bm=boneMap[b.name];
    if(!bm){ html+='<div class="bone-group"><div class="bone-label" style="color:#f44">❌ '+b.label+'</div></div>'; return; }
    html+='<div class="bone-group"><div class="bone-label">'+b.label+'</div>';
    b.keys.forEach(k=>{
      const id='sl_'+b.name+'_'+k;
      html+='<div class="slider-row">'+
        '<span class="axis">'+k.toUpperCase()+'</span>'+
        '<input type="range" id="'+id+'" data-bone="'+b.name+'" data-key="'+k+'" min="-3.2" max="3.2" step="0.01" value="'+(bm.rotation[k]||0)+'">'+
        '<span class="val" id="'+id+'_v">'+(bm.rotation[k]||0).toFixed(2)+'</span>'+
        '</div>';
    });
    html+='</div>';
  });
  scroll.innerHTML=html;
  scroll.querySelectorAll('input[type=range]').forEach(inp=>inp.addEventListener('input',handleSliderInput));
}

function syncSliders(){
  EDIT_BONES.forEach(b=>{const bm=boneMap[b.name];if(!bm)return;
    b.keys.forEach(k=>{const s=document.getElementById('sl_'+b.name+'_'+k),v=document.getElementById('sl_'+b.name+'_'+k+'_v'),val=bm.rotation[k]||0;if(s)s.value=val;if(v)v.textContent=val.toFixed(2)});
  });
}

function applyDelta(delta){
  for(const k in boneMap){const r=REST[k]; if(r) boneMap[k].rotation.set(r.x, r.y, r.z);}
  for(const k in delta){
    const b=boneMap[k]; if(!b)continue;
    const r=REST[k]||{x:0,y:0,z:0};
    const d=delta[k];
    b.rotation.set(r.x+(d.x||0), r.y+(d.y||0), r.z+(d.z||0));
  }
  if(skinnedMesh?.skeleton)skinnedMesh.skeleton.update();
  syncSliders();
}

function applyAbs(obj){for(const n in obj){const b=boneMap[n];if(!b)continue;const r=obj[n];if(r&&'x'in r)b.rotation.set(r.x||0,r.y||0,r.z||0)}if(skinnedMesh?.skeleton)skinnedMesh.skeleton.update();syncSliders()}
function getPose(){const p={};for(const k in boneMap)p[k]={x:boneMap[k].rotation.x,y:boneMap[k].rotation.y,z:boneMap[k].rotation.z};return p}

let tt;
function toast(m){const e=document.getElementById('toast');e.textContent=m;e.classList.add('show');if(tt)clearTimeout(tt);tt=setTimeout(()=>e.classList.remove('show'),2000)}

const PRESETS = {
  apose:()=>{applyDelta({});toast('A-Pose');},
  fist:()=>{applyDelta({rthumb:dg(-40,0,0),rindex:dg(-110,0,0),rmiddle:dg(-110,0,0),rring:dg(-110,0,0),rpinky:dg(-110,0,0)});toast('握拳');},
  flat:()=>{applyDelta({rthumb:dg(30,0,0),rindex:dg(30,0,0),rmiddle:dg(30,0,0),rring:dg(30,0,0),rpinky:dg(30,0,0)});toast('平掌');},
  point:()=>{applyDelta({rindex:dg(0,0,0),rthumb:dg(-40,0,0),rmiddle:dg(-110,0,0),rring:dg(-110,0,0),rpinky:dg(-110,0,0)});toast('食指指');},
  thumbUp:()=>{applyDelta({rthumb:{x:0,y:1.1,z:1.1}});toast('拇指竖');},
  抬头:()=>{applyDelta({head:dg(-43.9,0,0)});toast('抬头');},
  低头:()=>{applyDelta({head:dg(38.6,0,0)});toast('低头');},
  左转头:()=>{applyDelta({head:dg(1.4,-44.6,0)});toast('左转头');},
  右转头:()=>{applyDelta({head:dg(1.4,64.3,0)});toast('右转头');},
  左歪头:()=>{applyDelta({head:dg(1.4,-1.0,33.4)});toast('左歪头');},
  右歪头:()=>{applyDelta({head:dg(1.4,-1.0,-47.4)});toast('右歪头');},
};

const API = {
  resetAll(){applyDelta({});toast('A-Pose');},
  exportPose(){
    const j=JSON.stringify(getPose(),null,2);
    document.getElementById('output-text').textContent=j;
    navigator.clipboard.writeText(j).then(()=>toast('JSON已复制'));
  },
  exportAsCode(){
    const lines=[]; const delta={};
    for(const b of EDIT_BONES){
      if(!boneMap[b.name])continue;
      const cur=boneMap[b.name].rotation;
      const r=REST[b.name]||{x:0,y:0,z:0};
      const dx=+(cur.x-r.x)/D, dy=+(cur.y-r.y)/D, dz=+(cur.z-r.z)/D;
      if(Math.abs(dx)<0.3&&Math.abs(dy)<0.3&&Math.abs(dz)<0.3)continue;
      lines.push(b.name+': dg('+dx.toFixed(1)+','+dy.toFixed(1)+','+dz.toFixed(1)+'),');
      delta[b.name]={x:dx,y:dy,z:dz};
    }
    const code='applyDelta({\n  '+lines.join('\n  ')+'\n});';
    document.getElementById('output-text').textContent=code;
    navigator.clipboard.writeText(code).then(()=>toast('代码已复制'));
    const lib=document.getElementById('lib-name').value||'default';
    const name=prompt('手势名称？(库: '+lib+')','');
    if(name){
      const existing=JSON.parse(localStorage.getItem('sb_gestures')||'{}');
      existing[name]={library:lib, delta:delta, timestamp:new Date().toISOString()};
      localStorage.setItem('sb_gestures',JSON.stringify(existing,null,2));
      const libs={}; for(const [k,v] of Object.entries(existing)){ const l=v.library||'default'; if(!libs[l])libs[l]=[]; libs[l].push(k); }
      let txt='✅ '+name+' ['+lib+']\n'+code+'\n';
      for(const [l,names] of Object.entries(libs)){ txt+='\n📁 '+l+' ('+names.length+'): '+names.join(', '); }
      document.getElementById('output-text').textContent=txt;
      API.refreshLib(); toast('✅ 已保存: '+name+' → '+lib);
    }
  },
  importPose(){const t=prompt('粘贴JSON:');if(!t)return;try{applyAbs(JSON.parse(t));toast('已导入')}catch(e){toast('JSON错误:'+e.message)}},
  loadPreset(name){if(PRESETS[name]){PRESETS[name]();}else{toast('❌ 未知: '+name);}},
  showGestures(){
    const g=JSON.parse(localStorage.getItem('sb_gestures')||'{}');
    const libs={}; for(const [k,v] of Object.entries(g)){ const l=v.library||'default'; if(!libs[l])libs[l]=[]; libs[l].push(k); }
    let txt='全部 '+Object.keys(g).length+' 个手势:\n';
    for(const [l,names] of Object.entries(libs)){ txt+='\n📁 '+l+' ('+names.length+'): '+names.join(', '); }
    document.getElementById('output-text').textContent=txt;
    toast('共 '+Object.keys(g).length+' 个手势');
  },
  downloadGestures(){
    const g=JSON.parse(localStorage.getItem('sb_gestures')||'{}');
    const blob=new Blob([JSON.stringify(g,null,2)],{type:'application/json'});
    const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='signbridge-gestures.json';a.click();
    toast('已下载');
  },
  onSymToggle(){toast(document.getElementById('sym-mode').checked?'对称模式开':'对称模式关')},
  refreshLib(){
    const g=JSON.parse(localStorage.getItem('sb_gestures')||'{}');
    const libs={}; for(const [k,v] of Object.entries(g)){ const l=v.library||'default'; if(!libs[l])libs[l]=[]; libs[l].push(k); }
    let h='';
    for(const [l,names] of Object.entries(libs)){
      h+='<div style="color:#ff0;margin:4px 0 2px;">📁 '+l+'</div>';
      names.forEach(n=>{
        h+='<div style="display:flex;align-items:center;gap:4px;margin:1px 0;padding:2px 4px;background:#1a1a3a;border-radius:3px;cursor:pointer;" class="lib-item" data-gname="'+n+'" title="点击应用">';
        h+='<span style="flex:1;">'+n+'</span>';
        h+='<button style="font-size:9px;padding:1px 4px;background:#933;color:#fff;border:none;border-radius:2px;cursor:pointer;" class="lib-del" data-gname="'+n+'">🗑</button>';
        h+='</div>';
      });
    }
    if(!Object.keys(g).length) h='<div style="color:#888;">暂无，摆好姿势后点导出代码保存</div>';
    document.getElementById('lib-list').innerHTML=h;
    document.getElementById('lib-list').querySelectorAll('.lib-item').forEach(el=>{
      el.addEventListener('click',()=>{ API.applyLib(el.dataset.gname); });
    });
    document.getElementById('lib-list').querySelectorAll('.lib-del').forEach(el=>{
      el.addEventListener('click',(e)=>{ e.stopPropagation(); API.delLib(el.dataset.gname); });
    });
  },
  applyLib(name){
    const g=JSON.parse(localStorage.getItem('sb_gestures')||'{}');
    if(!g[name]){toast('❌ 未找到: '+name);return;}
    applyDelta(g[name].delta);
    toast('✅ '+name);
    document.getElementById('pose-label').textContent=name;
  },
  delLib(name){
    if(!confirm('删除 '+name+'?'))return;
    const g=JSON.parse(localStorage.getItem('sb_gestures')||'{}');
    delete g[name];
    localStorage.setItem('sb_gestures',JSON.stringify(g,null,2));
    this.refreshLib();
    toast('🗑 已删除: '+name);
  },
};

function bindUI(){
  document.getElementById('btn-reset').addEventListener('click',API.resetAll);
  document.getElementById('btn-export-json').addEventListener('click',API.exportPose);
  document.getElementById('btn-export-code').addEventListener('click',API.exportAsCode);
  document.getElementById('btn-import').addEventListener('click',API.importPose);
  document.getElementById('btn-show-all').addEventListener('click',API.showGestures);
  document.getElementById('btn-dl').addEventListener('click',API.downloadGestures);
  document.getElementById('preset-dd').addEventListener('change',function(){API.loadPreset(this.value)});
  document.getElementById('sym-mode').addEventListener('change',API.onSymToggle);document.getElementById('btn-refresh-lib').addEventListener('click',API.refreshLib);
}

(async()=>{
  window.__PE=API;
  window.addEventListener('resize',resize);
  resize();anim();
  bindUI();

  try{
    document.getElementById('load-status').textContent='⏳ 加载模型...';
    const gltf=await loadModel();
    document.getElementById('load-status').textContent='🔍 解析骨骼...';
    mapBones(gltf);
    modelRoot=gltf.scene;
    scene.add(modelRoot);
    camera.position.set(0, 1.2, 1.8);
    ctrl.target.set(0, 0.8, 0);
    ctrl.update();

    document.getElementById('pose-label').textContent='A-Pose ('+Object.keys(boneMap).length+' 骨骼)';
    document.getElementById('load-status').style.display='none';

    const dd=document.getElementById('preset-dd');
    dd.innerHTML='<option value="apose">A-Pose</option>'+
    '<optgroup label="手形">'+
    '<option value="fist">握拳</option>'+
    '<option value="flat">平掌</option>'+
    '<option value="point">食指指</option>'+
    '<option value="thumbUp">拇指竖</option>'+
    '</optgroup>'+
    '<optgroup label="头部">'+
    '<option value="抬头">抬头</option>'+
    '<option value="低头">低头</option>'+
    '<option value="左转头">左转头</option>'+
    '<option value="右转头">右转头</option>'+
    '<option value="左歪头">左歪头</option>'+
    '<option value="右歪头">右歪头</option>'+
    '</optgroup>';
    buildSliders();
  }catch(e){
    document.getElementById('load-status').textContent='❌ 失败: '+e.message;
    document.getElementById('load-status').style.color='#f44';
    document.getElementById('pose-label').textContent='加载失败';
    console.error(e);
  }
})();
