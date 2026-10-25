import * as THREE from 'three';
const GOLD=0xF4D9A0, BRONZE=0x5B4632, AMBER=0xCB792C;
// Every station/page/gateway is created from a record. Supports are architecture, not additional data.
export function buildEvidenceScene({root,kind,records,onAsset}) {
 const objects=[],groups=[],textures=[];
 const material=(color=BRONZE)=>new THREE.MeshStandardMaterial({color,metalness:.62,roughness:.38});
 const add=(g,w,h,d,x,y,z,color,index)=>{const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),material(color));m.position.set(x,y,z);g.add(m);if(index!==undefined){m.userData.index=index;objects.push(m)}return m};
 const title=(group,label,detail,y,z)=>{
  const c=document.createElement('canvas');c.width=1024;c.height=256;const ctx=c.getContext('2d');ctx.fillStyle='#211810';ctx.fillRect(0,0,1024,256);ctx.strokeStyle='#CB792C';ctx.lineWidth=4;ctx.strokeRect(6,6,1012,244);ctx.fillStyle='#F4D9A0';ctx.font='46px Georgia';ctx.fillText(label.slice(0,35),38,90);ctx.font='24px sans-serif';ctx.fillStyle='#d3bd99';ctx.fillText(detail.slice(0,65),38,155);
  const texture=new THREE.CanvasTexture(c);texture.colorSpace=THREE.SRGBColorSpace;textures.push(texture);const mesh=new THREE.Mesh(new THREE.PlaneGeometry(2.5,.625),new THREE.MeshBasicMaterial({map:texture}));mesh.position.set(0,y,z);group.add(mesh);
 };
 records.forEach((record,i)=>{
  const group=new THREE.Group();root.add(group);groups.push(group);
  const colour=record.state==='active'?AMBER:record.state==='broken'?0xcd7764:record.state==='anchored'||record.state==='checked'||record.state==='COMPLETED'||record.state==='APPROVED'?GOLD:BRONZE;
  if(kind==='route'){
   group.position.z=-i*3.8;
   // Each portal is a returned route stage, with no generated intermediate stages.
   add(group,.26,3.8,.55,-1.65,.7,0,colour,i);add(group,.26,3.8,.55,1.65,.7,0,colour,i);add(group,3.56,.3,.55,0,2.6,0,colour,i);
   add(group,3.8,.08,3.8,0,-1.25,-1.5,BRONZE);
   for(const x of [-1.49,1.49])add(group,.035,3.5,.03,x,.7,.29,record.state==='active'?GOLD:AMBER,i);
   title(group,`${String(i+1).padStart(2,'0')}  ${record.label}`,record.detail,1.85,.32);
  }else if(kind==='ocr'){
   group.position.set(i*.35,0,-i*.28);group.rotation.set(-.12,-.2,0);
   const ratio=(record.pageWidth||600)/(record.pageHeight||800),width=3.7*ratio;
   const page=add(group,width,3.7,.025,0,0,0,GOLD,i);
   if(record.imageUrl){const texture=new THREE.TextureLoader().load(record.imageUrl,()=>onAsset(),undefined,()=>{});texture.colorSpace=THREE.SRGBColorSpace;textures.push(texture);const surface=new THREE.Mesh(new THREE.PlaneGeometry(width,3.7),new THREE.MeshBasicMaterial({map:texture}));surface.position.z=.02;group.add(surface)}
   // Boxes enter this function only from resolved, committed suggestion state.
   (record.boxes||[]).forEach(box=>{
    const x=(box.x+box.w/2)/record.pageWidth*width-width/2,y=1.85-(box.y+box.h/2)/record.pageHeight*3.7;
    const mark=new THREE.Mesh(new THREE.PlaneGeometry(box.w/record.pageWidth*width,box.h/record.pageHeight*3.7),new THREE.MeshBasicMaterial({color:AMBER,transparent:true,opacity:.34,depthWrite:false}));mark.position.set(x,y,.045);group.add(mark);
   });
   title(group,record.label,record.detail,-2.35,.04);
  }else if(kind==='audit'){
   group.position.set((i-(records.length-1)/2)*3.15,0,0);
   add(group,2.7,.2,1.7,0,-1.2,0,BRONZE);
   add(group,2.45,2.5,.18,0,.15,0,colour,i);
   add(group,2.5,.05,.25,0,1.42,0,GOLD);
   title(group,record.label,record.detail,.7,.105);
   title(group,record.state==='unknown'?'NO ASSURANCE INFERRED':'RECORDED RESULT',record.facts?.[0]?.join(': ')||'See evidence register',-.1,.105);
  }
 });
 return {objects,textures,update(scroll,selected,camera,yaw,pitch,travel){
  const p=Math.min(1,scroll+travel/300),focus=Math.min(Math.max(0,records.length-1),selected);
  if(kind==='route'){
   const depth=p*Math.max(0,records.length-1)*3.8;
   camera.position.set(.75*(1-p)+yaw,1+pitch,6-depth);camera.lookAt(0,.7,-depth-2);
   groups.forEach((g,i)=>{g.children.filter(o=>o.isMesh&&o.material.emissive).forEach(o=>{o.material.emissive.setHex(i===focus?0x362513:0x000000);o.material.emissiveIntensity=.3})});
  }else if(kind==='ocr'){
   camera.position.set(1.8-p*1.5+yaw,1.4-p+pitch,7-p*1.8);camera.lookAt(0,0,-p*.5);
   groups.forEach((g,i)=>{g.position.x=i*(.35+p*.75);g.position.z=-i*(.28+p*.8);g.rotation.y=-.2+p*.15});
  }else{
   const x=(p-.5)*Math.max(0,records.length-1)*3.15;
   camera.position.set(x+yaw,1.5+pitch,8-p*2);camera.lookAt(x,.2,0);
  }
 }};
}
