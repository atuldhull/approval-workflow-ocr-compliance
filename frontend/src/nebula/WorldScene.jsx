import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { buildEvidenceScene } from './buildEvidenceScene.js';

// One GPU context per visible world. Procedural geometry only; no external assets.
export default function WorldScene({ kind, records, selected, onSelect, travel, cameraControl, reduced, onFailure }) {
  const host = useRef(null); const live = useRef({selected,travel,reduced,records,onSelect});
  live.current={selected,travel,reduced,records,onSelect};
  const signature=JSON.stringify(records);
  useEffect(()=>{
    const el=host.current; let renderer; let disposed=false;
    try { renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'low-power'}); } catch {onFailure();return;}
    renderer.setPixelRatio(Math.min(window.devicePixelRatio,window.innerWidth<700?1.25:1.65));
    renderer.setClearColor(0x000000,0);renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.2;
    el.appendChild(renderer.domElement);renderer.domElement.setAttribute('aria-hidden','true');
    const scene=new THREE.Scene(); const camera=new THREE.PerspectiveCamera(43,1,.1,100);
    camera.position.set(2.6,2.6,7.2);camera.lookAt(0,0,0);
    const root=new THREE.Group();scene.add(root);
    scene.add(new THREE.HemisphereLight(0xF4D9A0,0x21150e,.65));
    const key=new THREE.DirectionalLight(0xF4D9A0,6);key.position.set(4,7,2);scene.add(key);
    const rim=new THREE.DirectionalLight(0xCB792C,4);rim.position.set(-4,-1,-3);scene.add(rim);
    const evidence=buildEvidenceScene({root,kind,records,onAsset:()=>{if(!disposed&&el.isConnected)renderer.render(scene,camera)}});
    const objects=evidence.objects;
    el.dataset.recordIds=JSON.stringify(records.map(r=>r.id));el.dataset.recordStates=JSON.stringify(records.map(r=>r.state));el.dataset.elementCount=records.length;
    let lastState='';
    const resize=()=>{const width=el.clientWidth,height=el.clientHeight;renderer.setSize(width,height,false);camera.aspect=width/Math.max(1,height);camera.updateProjectionMatrix();lastState='';renderer.render(scene,camera);el.dataset.rendered='true';el.dataset.drawCalls=renderer.info.render.calls;};
    const ro=new ResizeObserver(resize);ro.observe(el);resize();
    let visible=true,raf=0,last=0,down=null,dragged=false;
    const io=new IntersectionObserver(([e])=>{visible=e.isIntersecting;if(visible)start();else{cancelAnimationFrame(raf);raf=0;}},{rootMargin:'80px'});io.observe(el);
    const ray=new THREE.Raycaster();const pointer=new THREE.Vector2();
    const onDown=e=>{down={x:e.clientX,y:e.clientY};dragged=false;el.setPointerCapture(e.pointerId);};
    const onMove=e=>{if(!down)return;const dx=e.clientX-down.x,dy=e.clientY-down.y;if(Math.abs(dx)+Math.abs(dy)>2)dragged=true;cameraControl.current.yaw+=dx*.006;cameraControl.current.pitch=Math.max(-.6,Math.min(.7,cameraControl.current.pitch+dy*.004));down={x:e.clientX,y:e.clientY};};
    const onUp=e=>{if(!dragged){const r=el.getBoundingClientRect();pointer.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);ray.setFromCamera(pointer,camera);const hit=ray.intersectObjects(objects)[0];if(hit)live.current.onSelect(hit.object.userData.index);}down=null;};
    el.addEventListener('pointerdown',onDown);el.addEventListener('pointermove',onMove);el.addEventListener('pointerup',onUp);el.addEventListener('pointercancel',onUp);
    const lost=e=>{e.preventDefault();onFailure();};renderer.domElement.addEventListener('webglcontextlost',lost);
    const tick=time=>{
      raf=0;if(disposed||!visible||document.hidden)return;
      // 30fps ceiling; static/reduced mode renders only if input changed.
      if(time-last>32){
        const {travel,selected,reduced}=live.current;const r=el.getBoundingClientRect();const scroll=reduced?0:Math.max(0,Math.min(1,window.scrollY/Math.max(1,document.documentElement.scrollHeight-window.innerHeight)));const p=Math.min(1,travel/100+scroll*.8);
        const yaw=cameraControl.current.yaw, pitch=cameraControl.current.pitch;
        const state=[travel,selected,reduced,scroll,yaw,pitch,el.clientWidth,el.clientHeight].join(',');
        if(state===lastState) { raf=requestAnimationFrame(tick); return; }
        lastState=state;
        evidence.update(scroll,selected,camera,yaw,pitch,travel);
        el.dataset.scrollProgress=scroll.toFixed(4);el.dataset.camera=camera.position.toArray().map(n=>n.toFixed(3)).join(',');
        renderer.render(scene,camera);last=time;el.dataset.rendered='true';el.dataset.drawCalls=renderer.info.render.calls;
      }
      raf=requestAnimationFrame(tick);
    };
    function start(){if(!raf&&!disposed&&!document.hidden)raf=requestAnimationFrame(tick);}
    const visibility=()=>{if(document.hidden){cancelAnimationFrame(raf);raf=0;}else start();};document.addEventListener('visibilitychange',visibility);start();
    return()=>{disposed=true;cancelAnimationFrame(raf);io.disconnect();ro.disconnect();document.removeEventListener('visibilitychange',visibility);el.removeEventListener('pointerdown',onDown);el.removeEventListener('pointermove',onMove);el.removeEventListener('pointerup',onUp);el.removeEventListener('pointercancel',onUp);renderer.domElement.removeEventListener('webglcontextlost',lost);scene.traverse(o=>{o.geometry?.dispose();if(o.material){(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>m.dispose());}});evidence.textures.forEach(t=>t.dispose());renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();};
  },[kind,signature]);
  return <div className="nebula-canvas" ref={host} data-scene={kind} />;
}
