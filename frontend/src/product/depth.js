import {useEffect,useRef} from 'react';
import {useReducedMotion} from '../motion.js';
// Visual depth follows viewport position, never backend state. No idle animation loop.
export function useInstrumentDepth(){
 const ref=useRef(null);const reduced=useReducedMotion();
 useEffect(()=>{const el=ref.current;if(!el)return;let frame=0;
 const draw=()=>{frame=0;const r=el.getBoundingClientRect();const p=reduced ? .5 : Math.max(0,Math.min(1,(innerHeight-r.top)/(innerHeight+r.height)));el.style.setProperty('--depth',p.toFixed(3));el.dataset.depth=p.toFixed(3)};
 const update=()=>{if(!frame)frame=requestAnimationFrame(draw)};draw();window.addEventListener('scroll',update,{passive:true});window.addEventListener('resize',update);return()=>{cancelAnimationFrame(frame);window.removeEventListener('scroll',update);window.removeEventListener('resize',update);};
 },[reduced]);return ref;
}
