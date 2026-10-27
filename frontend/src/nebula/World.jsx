import { Component, Suspense, lazy, useEffect, useRef, useState } from 'react';
import { useReducedMotion } from '../motion.js';
import { datePositions } from './semanticData.js';
import { when } from '../components/ui.jsx';
// Due dates arrive as plain dates; recorded moments (submission) as full timestamps, shown in IST like everywhere else.
const showDate = d => /^\d{4}-\d{2}-\d{2}$/.test(String(d)) || Number.isNaN(Date.parse(d)) ? String(d ?? '') : when(d);
const Scene=lazy(()=>import('./WorldScene.jsx'));
class SceneBoundary extends Component {state={failed:false};static getDerivedStateFromError(){return{failed:true}}render(){return this.state.failed?<p className="world-fallback">The spatial renderer is unavailable. All evidence remains in the register.</p>:this.props.children}}
export const WORLDS={
 overview:['01','Institution workflow','Your applications, in context.','One lane per application. The pointer marks its recorded current stage; earlier positions are not proof of approval.'],
 applications:['02','Case portfolio','Choose a case to examine.','Each dossier is an existing application. Open one to follow its prescribed route and recorded history.'],
 route:['03','Approval journey','A route through review.','Each gateway is a stage returned for this case. Scroll to inspect the route; its recorded state stays unchanged.'],
 dashboard:['04','Regional scope','The scope of review.','Each span represents one supplied region. Width is proportional to its application count; no absent regions are added.'],
 officer:['05','Review register','Work, grouped by age.','These are reported age buckets, not an assigned work queue or priority ranking. Age alone does not establish that a case is overdue.'],
 inbox:['06','Notification provenance','From category to message.','Each connection links a recorded template category to its notification. Specific triggering events are not inferred.'],
 delivery:['07','Message delivery','What happened to each message.','Each lane ends at the reported state. Inspect recorded attempts for a message; scrolling never simulates delivery.'],
 audit:['08','Assurance layers','Three different questions of trust.','Continuity, independent anchoring and replay answer different questions. No single result substitutes for the others.'],
 ocr:['09','Evidence inspection','Read the source. Then compare.','The document is the evidence. Machine locations and comparisons appear only after you commit the corresponding independent reading.'],
 facts:['09','Fact register','Read the source. Then compare.','One record per extracted fact, showing only its review state. A machine reading appears below only after you commit your own.'],
 documents:['13','Document quarantine','Every version, and what the scan found.','One record per checklist document. A version is usable only after the malware scan reports it clean; older versions stay on record.'],
 alerts:['14','Alert ladder','Who was told, and who answered.','One record per raised alert level. Escalation follows the configured ladder; acknowledging stops it for that due date.'],
 evc:['10','Candidate visit timeline','Coordinate a visit.','Candidate dates occupy their relative positions on an IST time axis. These sample slots are not confirmed visits.'],
 compliance:['11','Obligation archive','An obligation. Its evidence.','Each compartment represents one recorded obligation. Submitted evidence and its verification remain separate; only acceptance by an officer meets it.'],
 scorecard:['12','Evaluation evidence','What has actually been tested.','Measurement method and outcome are separate. A category without a result remains unevaluated.'],
};
export default function World({kind,records=[],preview=false,onSelect,actionLabel='Open selected case',compact=false}){
 const meta=WORLDS[kind]||WORLDS.overview;const reduced=useReducedMotion();const [flat,setFlat]=useState(()=>{try{return localStorage.getItem('nebula.flat')==='true'}catch{return false}});
 const [selected,setSelected]=useState(0),[progress,setProgress]=useState(0),[travel,setTravel]=useState(0),[failed,setFailed]=useState(false);const camera=useRef({yaw:0,pitch:0});const section=useRef(null);const manual=useRef(false);const [pinned,setPinned]=useState(false);
 const spatial=['route','ocr','audit'].includes(kind);const webgl=typeof window!=='undefined'&&typeof window.WebGL2RenderingContext!=='undefined';
 const use3d=spatial&&webgl&&!flat&&!failed&&records.length>0;const limit=Math.min(24,records.length);const index=Math.min(selected,Math.max(0,limit-1));const record=records[index];
 useEffect(()=>{let frame=0;const update=()=>{frame=0;const p=reduced?0:Math.max(0,Math.min(1,window.scrollY/Math.max(1,document.documentElement.scrollHeight-innerHeight)));setProgress(p);if(!reduced&&!manual.current)setSelected(Math.min(Math.max(0,limit-1),Math.floor(p*limit)));};const scroll=()=>{if(!frame)frame=requestAnimationFrame(update)};window.addEventListener('scroll',scroll,{passive:true});return()=>{window.removeEventListener('scroll',scroll);cancelAnimationFrame(frame)}},[reduced,limit]);
 const pick=i=>{manual.current=true;setPinned(true);setSelected(i)};const changeMode=()=>{setFlat(!flat);try{localStorage.setItem('nebula.flat',String(!flat))}catch{}};
 const positions=datePositions(records);
 return <section ref={section} className={`semantic-world semantic-${kind} ${spatial?'semantic-spatial':'semantic-plan'}${flat?' is-standard':''}${compact?' semantic-compact':''}`} data-semantic={kind} data-progress={progress.toFixed(4)} data-focus-id={record?.id} aria-label={meta[1]} style={{'--story-progress':progress}}>
  <header className="semantic-heading"><p className="world-coordinate">{meta[0]} / {meta[1]} {preview&&<strong>PREVIEW · SAMPLE</strong>}</p><h2>{meta[2]}</h2><p>{meta[3]}</p></header>
  <div className="semantic-toolbar"><span>{records.length} {kind==='route'?'prescribed stages':kind==='ocr'?'source pages':'available records'} · {reduced?'Motion paused':'Scroll to inspect · no status changes'}</span>{pinned&&<button className="ghost small" onClick={()=>{manual.current=false;setPinned(false);setSelected(Math.min(Math.max(0,limit-1),Math.floor(progress*limit)))}}>Follow scroll</button>}<button className="ghost small" onClick={changeMode}>{flat?'Spatial view':'Standard view'}</button></div>
  {use3d&&<div className="world-viewport" tabIndex={0} role="group" aria-label={`${meta[1]} spatial explorer. Arrow keys rotate. Plus and minus adjust camera. Home resets.`} onKeyDown={e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','Home'].includes(e.key)){e.preventDefault();if(e.key==='Home'){camera.current={yaw:0,pitch:0};setTravel(0)}else if(e.key==='+'||e.key==='-')setTravel(v=>Math.max(0,Math.min(100,v+(e.key==='+'?10:-10))));else{camera.current.yaw+=e.key==='ArrowLeft'?-.15:e.key==='ArrowRight'?.15:0;camera.current.pitch+=e.key==='ArrowUp'?.1:e.key==='ArrowDown'?-.1:0;}}}}><SceneBoundary><Suspense fallback={<p>Preparing evidence environment…</p>}><Scene kind={kind} records={records.slice(0,24)} selected={index} onSelect={pick} travel={travel} cameraControl={camera} reduced={reduced} onFailure={()=>setFailed(true)}/></Suspense></SceneBoundary></div>}
  {!use3d&&<p className="semantic-mode">{spatial&&(!webgl||failed)?'WebGL unavailable · standard view':flat?'Standard view · rendering disabled':'Labelled evidence view'}</p>}
  {kind==='evc'&&<div className="schedule-axis" role="group" aria-label="Candidate dates placed proportionally">{records.map((r,i)=>positions[i]!==null&&<time className="schedule-pin" key={r.id} dateTime={r.date} style={{left:`${positions[i]}%`}}>{r.dateLabel}</time>)}</div>}
  <div className="semantic-register" role="group" aria-label={`${meta[1]} records`} data-record-count={records.length}>
   {records.slice(0,24).map((r,i)=><button key={r.id||i} className={`semantic-record record-${r.state||'unknown'}`} data-record-id={r.id} data-record-state={r.state||''} aria-pressed={index===i} onClick={()=>pick(i)} style={{'--item':i,'--quantity':Math.max(0,Number(r.value)||0)/Math.max(1,...records.map(x=>Number(x.value)||0)),'--date-position':`${positions[i]??50}%`}}>
    <span className="semantic-number">{String(i+1).padStart(2,'0')}</span>
    {kind==='inbox'&&<span className="source-category">{r.category||r.label}<span aria-hidden="true"> → </span></span>}
    <strong>{r.label}</strong><span className="semantic-state">{r.detail}</span>
    {typeof r.value==='number'&&<span className="quantity"><i/><b>{r.value}</b></span>}
    {r.stages&&<span className="application-path">{r.stages.length?r.stages.map((s,j)=><span key={j} className={s.current?'at-stage':''}>{s.label}{s.current?' · current':''}</span>):<span>No route assigned</span>}</span>}
    {kind==='compliance'&&<span className={`evidence-tab ${r.evidence?'has-file':''}`}>{r.evidence||'No evidence supplied'}</span>}
    {kind==='ocr'&&r.imageUrl&&<img src={r.imageUrl} alt={`Source page ${i+1}; inspect the full image below`} />}
    {kind==='delivery'&&<span className="delivery-stop">Reported outcome: {r.state} · {r.attemptCount??'—'} recorded attempts</span>}
    {kind==='evc'&&<span className="date-pin">{r.dateLabel}</span>}
   </button>)}
  </div>
  {records.length>24&&<p className="source">Showing the first 24 records in this visual register. The complete operational list is below.</p>}
  <aside className="semantic-inspection" aria-label="Focused record details">
   <p className="inspection-caption">INSPECTING / {record?String(index+1).padStart(2,'0'):'—'} <span>Selection is not a decision</span></p>
   <h3>{record?.label||'No records to explore'}</h3><p className="inspection-state">{record?.detail||'No source records are available. Nothing is inferred.'}</p>
   {record?.facts&&<dl>{record.facts.map(([label,value],i)=><div key={i}><dt>{label}</dt><dd>{String(value??'Not supplied')}</dd></div>)}</dl>}
   {onSelect&&record&&<button className="world-open" onClick={()=>onSelect(record.id)}>{actionLabel} <span aria-hidden="true">↗</span></button>}
  </aside>
  {kind==='route'&&<p className="semantic-limit">Gateways show the prescribed route, not a recorded transition graph. Stage completion evidence and a deficiency return path are not supplied; neither is inferred.</p>}
  {kind==='audit'&&<p className="semantic-limit">The API supplies assurance summaries, not full ledger events. No synthetic event sequence is drawn from the checked-entry count.</p>}
  <div className="story-footer"><span>SCROLL / INSPECT / RETURN</span><span>{preview?'PREVIEW — no operational decision':'Recorded states remain unchanged'}</span></div>
 </section>
}
export function DeadlineTimeline({deadlines=[],submittedAt}){
 const records=[...(submittedAt?[{id:'submitted',date:submittedAt,label:'Submitted',status:'Recorded timestamp'}]:[]),...deadlines.map(d=>({id:d.id,date:d.due_date,label:d.rule_id,status:d.status}))];const positions=datePositions(records);
 if(!records.length)return null;
 return <figure className="responsibility-timeline"><figcaption>Recorded dates · spacing reflects available dates only</figcaption><div className="date-axis" aria-hidden="true">{records.map((r,i)=>positions[i]!==null&&<i key={r.id} style={{left:`${positions[i]}%`}} />)}</div><ol>{records.map((r,i)=><li key={r.id}><strong>{showDate(r.date)}</strong><span>{r.label} · {r.status}</span>{positions[i]===null&&<em>Date could not be placed on the axis</em>}</li>)}</ol><p>No start date or statutory duration is inferred. Source explanations remain below.</p></figure>
}
