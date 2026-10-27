import * as THREE from 'three';
const GOLD=0xF4D9A0,BRONZE=0x5B4632,AMBER=0xCB792C;
export function buildEvidenceScene({root,kind,records,onAsset}) {
 const objects=[],groups=[],textures=[],n=records.length;
 const material=(color=BRONZE)=>new THREE.MeshStandardMaterial({color,metalness:.48,roughness:.32});
 const add=(g,w,h,d,x,y,z,color,index)=>{
  const shape=new THREE.Shape();shape.moveTo(-w/2,-h/2);shape.lineTo(w/2,-h/2);shape.lineTo(w/2,h/2);shape.lineTo(-w/2,h/2);shape.closePath();
  const geom=new THREE.ExtrudeGeometry(shape,{depth:d,bevelEnabled:true,bevelSize:Math.min(.035,w/8,h/8),bevelThickness:.018,bevelSegments:1,steps:1});geom.translate(0,0,-d/2);
  const mesh=new THREE.Mesh(geom,material(color));mesh.position.set(x,y,z);g.add(mesh);
  if(index!==undefined){mesh.userData.index=index;objects.push(mesh)}return mesh;
 };
 const label=(g,text,x,y,z,width=1.8)=>{
  const c=document.createElement('canvas');c.width=768;c.height=128;const ctx=c.getContext('2d');
  ctx.fillStyle='#F4D9A0';ctx.font='34px sans-serif';ctx.fillText(text.slice(0,38),16,72);
  const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;textures.push(t);
  const m=new THREE.Mesh(new THREE.PlaneGeometry(width,width/6),new THREE.MeshBasicMaterial({map:t,transparent:true,depthWrite:false}));m.position.set(x,y,z);g.add(m);
 };
 const rail=(g,x,y,z,w)=>add(g,w,.025,.03,x,y,z,AMBER);
 records.forEach((r,i)=>{
  const g=new THREE.Group();root.add(g);groups.push(g);
  const col=r.state==='active'?AMBER:BRONZE;
  if(kind==='route'){
   g.position.z=-i*2.9;
   add(g,.18,3.8,.3,-1.5,.2,0,col,i);add(g,.18,3.8,.3,1.5,.2,0,col,i);add(g,3.18,.18,.3,0,2.1,0,col,i);
   rail(g,0,-1.7,-1.3,3.3);add(g,3.25,.04,2.9,0,-1.72,-1.3,BRONZE);
   for(const x of [-1.4,1.4])add(g,.025,3.6,.025,x,.2,.17,GOLD);
   label(g,`${String(i+1).padStart(2,'0')} / ${r.label}`,0,1.65,.2,2.6);
  }else if(kind==='ocr'){
   g.position.set(i*.3,0,-i*.3);g.rotation.set(-.08,-.25,0);
   const w=3.5*(r.pageWidth||600)/(r.pageHeight||800);add(g,w,3.5,.045,0,0,0,GOLD,i);
   if(r.imageUrl){const t=new THREE.TextureLoader().load(r.imageUrl,onAsset,undefined,()=>{});t.colorSpace=THREE.SRGBColorSpace;textures.push(t);const m=new THREE.Mesh(new THREE.PlaneGeometry(w,3.5),new THREE.MeshBasicMaterial({map:t}));m.position.z=.045;g.add(m)}
   (r.boxes||[]).forEach(b=>{const m=new THREE.Mesh(new THREE.PlaneGeometry(b.w/r.pageWidth*w,b.h/r.pageHeight*3.5),new THREE.MeshBasicMaterial({color:AMBER,transparent:true,opacity:.35,depthWrite:false}));m.position.set((b.x+b.w/2)/r.pageWidth*w-w/2,1.75-(b.y+b.h/2)/r.pageHeight*3.5,.07);g.add(m)});
  }else if(kind==='dashboard'){
   const max=Math.max(1,...records.map(r=>Number(r.value)||0)),h=Number(r.value)/max*3.5;
   g.position.x=(i-(n-1)/2)*1.1;
   if(h>0){add(g,.75,h,.45,0,h/2-1.5,0,BRONZE,i);add(g,.75,.035,.46,0,h-1.5,0,GOLD)}
   rail(g,0,-1.6,0,.95);label(g,`${r.label} / ${r.value}`,0,-1.95,.25,1.05);
  }else if(kind==='audit'){
   g.position.set((i-(n-1)/2)*1.5,0,-i*.4);g.rotation.y=-.2;
   // One independent assurance plane per actual summary/checkpoint.
   add(g,1.3,3.1,.12,0,0,0,BRONZE,i);add(g,1.32,.04,.15,0,1.55,0,GOLD);
   for(let j=0;j<3;j++)rail(g,0,.45-j*.32,.08,.9);
   label(g,String(i+1).padStart(2,'0'),0,1.08,.09,1.15);
   label(g,r.label,0,-1,.09,1.2);
   add(g,1.5,.12,1.2,0,-1.7,0,BRONZE);
  }else{
   // Indexed dossier leaves; only real source records create a leaf.
   const spread=Math.min(n,8);g.position.set((i%8-(spread-1)/2)*.7,Math.floor(i/8)*-.25,-i*.22);g.rotation.set(-.2,-.3,-.05);
   const outline=new THREE.Shape();outline.moveTo(-1.025,-1.4);outline.lineTo(1.025,-1.4);outline.lineTo(1.025,1.05);outline.lineTo(.675,1.4);outline.lineTo(-1.025,1.4);outline.closePath();
   const leaf=new THREE.Mesh(new THREE.ExtrudeGeometry(outline,{depth:.055,bevelEnabled:true,bevelSize:.018,bevelThickness:.012,bevelSegments:1,steps:1}),material(i===0?0x99744a:BRONZE));leaf.userData.index=i;objects.push(leaf);g.add(leaf);
   const fold=new THREE.Shape();fold.moveTo(.675,1.4);fold.lineTo(.675,1.05);fold.lineTo(1.025,1.05);fold.closePath();const corner=new THREE.Mesh(new THREE.ShapeGeometry(fold),material(GOLD));corner.position.z=.07;g.add(corner);
   add(g,.65,.18,.07,-.6,1.47,0,GOLD);
   label(g,String(i+1).padStart(2,'0'),-.2,1.04,.05,1.65);
   label(g,r.label,0,-.95,.05,1.8);
   if(r.stages){r.stages.slice(0,9).forEach((s,j)=>{add(g,.055,.055,.04,-.75+j*.18,.25,.07,s.current?GOLD:AMBER);if(j<r.stages.length-1&&j<8)rail(g,-.66+j*.18,.25,.06,.12)})}
   if(kind==='compliance'&&r.evidence){add(g,1.65,1.7,.025,0,.1,.08,0x9d835a);label(g,'EVIDENCE',0,.05,.11,1.5)}
   else for(let j=0;j<3;j++)rail(g,-.15,.05-j*.22,.05,1.15-j*.16);
  }
 });
 return {objects,textures,update(scroll,selected,camera,yaw,pitch,travel){
  const p=Math.min(1,scroll+travel/300),wide=Math.max(1,n/5);
  if(kind==='route'){
   const depth=p*Math.max(0,n-1)*2.9;camera.position.set(2.5*(1-p)+yaw,1.5+pitch,7-depth);camera.lookAt(0,.2,-depth-1);
  }else if(kind==='ocr'){
   camera.position.set(2.1-p*1.7+yaw,1.3-p*.8+pitch,7.3-p*1.2);camera.lookAt(0,0,0);
   groups.forEach((g,i)=>{g.position.x=i*(.3+p*.7);g.position.z=-i*(.3+p*.5);g.rotation.y=-.25+p*.2});
  }else if(kind==='audit'){
   camera.position.set(3.5-p*5+yaw,2.6-p+pitch,Math.max(8,n*2));camera.lookAt(0,0,-n*.2);
   groups.forEach((g,i)=>{g.position.z=-i*(.4+p*.5);g.rotation.y=-.2+p*.3});
  }else if(kind==='dashboard'){
   camera.position.set(3-p*4+yaw,2.7-p+pitch,Math.max(8,n*1.7));camera.lookAt(0,0,0);
  }else{
   camera.position.set(3.3-p*3+yaw,2-p*.6+pitch,6.2+Math.min(2,n*.05));camera.lookAt(0,0,-n*.1);
   groups.forEach((g,i)=>{g.position.x=(i%8-(Math.min(n,8)-1)/2)*(.7+p*.5);g.rotation.y=-.3+p*.45;g.rotation.z=-.05+(i%8-3)*p*.025});
  }
  groups.forEach((g,i)=>g.traverse(o=>{if(o.material?.emissive){o.material.emissive.setHex(i===selected?0x372711:0);o.material.emissiveIntensity=.25}}));
 }};
}
