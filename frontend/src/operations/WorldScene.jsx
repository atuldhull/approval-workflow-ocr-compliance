import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { buildEvidenceScene } from './buildEvidenceScene.js';

// A demand-rendered scene: no animation loop, no React reconciliation per pixel of scroll.
export default function WorldScene({ kind, records, selected, onSelect, travel, cameraControl, reduced, onFailure }) {
 const host=useRef(null), invalidate=useRef(()=>{}), live=useRef({});
 live.current={selected,travel,reduced,onSelect};
 const signature=JSON.stringify(records);
 useEffect(()=>invalidate.current(),[selected,travel,reduced]);
 useEffect(()=>{
  const el=host.current; let renderer;
  try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'low-power'})}catch{onFailure();return}
  renderer.setPixelRatio(Math.min(window.devicePixelRatio,window.innerWidth<700?1:1.5));
  renderer.setClearColor(0,0);renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.15;
  el.appendChild(renderer.domElement);renderer.domElement.setAttribute('aria-hidden','true');
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(38,1,.1,180),root=new THREE.Group();scene.add(root);
  scene.add(new THREE.HemisphereLight(0xF4D9A0,0x17130e,1.4));
  const key=new THREE.DirectionalLight(0xF4D9A0,5);key.position.set(-3,7,4);scene.add(key);
  const rim=new THREE.DirectionalLight(0xCB792C,3);rim.position.set(4,2,-3);scene.add(rim);
  let disposed=false,visible=true,raf=0,lastState='',frames=0,evidence;
  function draw(){
   raf=0;if(disposed||!visible||document.hidden||!evidence)return;
   const {selected,travel,reduced}=live.current;
   const scroll=reduced?0:Math.max(0,Math.min(1,window.scrollY/Math.max(1,document.documentElement.scrollHeight-innerHeight)));
   const {yaw,pitch}=cameraControl.current;
   const state=[selected,travel,reduced,scroll,yaw,pitch,el.clientWidth,el.clientHeight].join(',');
   if(state===lastState)return;lastState=state;
   evidence.update(scroll,selected,camera,yaw,pitch,travel);
   renderer.render(scene,camera);frames++;
   Object.assign(el.dataset,{rendered:'true',scrollProgress:scroll.toFixed(4),camera:camera.position.toArray().map(n=>n.toFixed(3)).join(','),drawCalls:String(renderer.info.render.calls),frames:String(frames)});
  }
  function schedule(){if(!raf&&!disposed&&visible&&!document.hidden)raf=requestAnimationFrame(draw)}
  invalidate.current=schedule;
  evidence=buildEvidenceScene({root,kind,records,onAsset:()=>{lastState='';schedule()}});
  Object.assign(el.dataset,{recordIds:JSON.stringify(records.map(r=>r.id)),recordStates:JSON.stringify(records.map(r=>r.state)),elementCount:String(records.length)});
  const resize=()=>{const w=el.clientWidth,h=el.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/Math.max(1,h);camera.updateProjectionMatrix();lastState='';schedule()};
  const ro=new ResizeObserver(resize);ro.observe(el);resize();
  const io=new IntersectionObserver(([e])=>{visible=e.isIntersecting;if(visible)schedule();else{cancelAnimationFrame(raf);raf=0}},{rootMargin:'60px'});io.observe(el);
  const visibility=()=>{if(document.hidden){cancelAnimationFrame(raf);raf=0}else schedule()};
  const lost=e=>{e.preventDefault();onFailure()};
  // Keyboard controls are hosted on the accessible viewport; pointer movement is optional.
  const keys=()=>schedule();el.parentElement.addEventListener('keydown',keys);
  window.addEventListener('scroll',schedule,{passive:true});document.addEventListener('visibilitychange',visibility);
  renderer.domElement.addEventListener('webglcontextlost',lost);schedule();
  return()=>{
   disposed=true;invalidate.current=()=>{};cancelAnimationFrame(raf);io.disconnect();ro.disconnect();
   window.removeEventListener('scroll',schedule);document.removeEventListener('visibilitychange',visibility);el.parentElement?.removeEventListener('keydown',keys);renderer.domElement.removeEventListener('webglcontextlost',lost);
   scene.traverse(o=>{o.geometry?.dispose();if(o.material)(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>m.dispose())});
   evidence.textures.forEach(t=>t.dispose());renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();
  };
 },[kind,signature]);
 return <div className="operations-canvas" ref={host} data-scene={kind}/>;
}
