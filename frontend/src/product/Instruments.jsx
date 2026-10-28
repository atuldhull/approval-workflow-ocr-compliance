import {DossierSculpture} from './DossierSculpture.jsx';
import {useInstrumentDepth} from "./depth.js";
import { useState } from 'react';
import { useCaseList } from '../views/ApplicationsView.jsx';
import { canAcknowledge } from '../views/AlertsView.jsx';
import { useApi, ErrorBox, Loading } from '../components/ui.jsx';
import { stageLabel } from '../components/RouteJourney.jsx';
import { internalRef } from '../provenance.js';


export default function OperationsPulse({who, me, counts, onNavigate}) {
  const depth = useInstrumentDepth();
  const cases = useCaseList(who, me);
  const alerts = useApi(who, '/alerts');
  const [chosen, setChosen] = useState('');
  const [stage, setStage] = useState(null);
  const selected = cases.data?.find(c => c.id === chosen) ?? cases.data?.find(c => c.status === 'IN_PROCESS');
  // Keying the reader prevents a previous case's response from being drawn under a newly selected reference.
  return <section className="pulse-layout" aria-label="Operations pulse">
    <div className="pulse-map" ref={depth}>
      <header className="pulse-heading"><div><span className="eyebrow">OPERATIONS PULSE</span><h2>Every decision.<br/>A traceable path.</h2></div><button onClick={() => onNavigate?.('applications')}>Open cases <span aria-hidden="true">↗</span></button></header>
      <label className="pulse-choice">Inspect an accessible case<select value={selected?.id ?? ''} onChange={e => {setChosen(e.target.value);setStage(null)}}><option value="" disabled>Select case</option>{cases.data?.filter(c => c.status !== 'DRAFT').map(c => <option value={c.id} key={c.id}>{internalRef(c.id)} · {c.category}</option>)}</select></label>
      <ErrorBox error={cases.error} onRetry={cases.reload}/>
      {cases.loading && !cases.data && <Loading rows={2}/>}
      {selected ? <PulseRoute key={selected.id} who={who} id={selected.id} counts={counts} stage={stage} setStage={setStage} onNavigate={onNavigate}/> : <p className="pulse-empty">No accessible in-process case is reported. A route will appear when a case supplies its prescribed stages.</p>}
      <p className="pulse-source">Route: selected case record. Figures: analytics stage projection across this scope, all categories; not counts for this case. Missing values are not zero. Earlier stages do not imply completion.</p>
    </div>
    <aside className="attention-desk"><span className="eyebrow">YOUR ACTION QUEUE</span><h2>Needs attention</h2><p className="muted small">Open or escalated alerts assigned to your role.</p><ErrorBox error={alerts.error} onRetry={alerts.reload}/>{alerts.loading && <Loading rows={2}/>}
      {alerts.data && <><strong className="attention-number">{alerts.data.filter(a=>canAcknowledge(a,me.role)).length}</strong>{alerts.data.filter(a=>canAcknowledge(a,me.role)).slice(0,3).map(a=><button key={a.id} className="attention-row" onClick={()=>onNavigate?.('alerts')}><span>{a.rule_id ?? a.template}</span><span className="badge warn">{a.status}</span></button>)}{!alerts.data.some(a=>canAcknowledge(a,me.role)) && <p>No alerts await acknowledgement by this role.</p>}</>}
      <button className="secondary" onClick={()=>onNavigate?.('alerts')}>View alert register →</button>
    </aside>
  </section>
}
function PulseRoute({who,id,counts,stage,setStage,onNavigate}) {
 const c=useApi(who,`/cases/${id}`);
 const route=c.data?.route ?? [];
 const focus=route.find(s=>s.stage===stage) ?? route.find(s=>s.stage===c.data?.stage) ?? route[0];
 return <><ErrorBox error={c.error} onRetry={c.reload}/>{c.loading && <Loading rows={2}/>}<div className="route-atlas"><DossierSculpture route={route} current={c.data?.stage}/><ol className="pulse-track" aria-label="Prescribed case stages">{route.map((s,i)=><li key={s.stage}><button title={`${stageLabel(s.stage)}${s.when==='as_applicable'?' · conditional':''}`} aria-pressed={focus?.stage===s.stage} className={s.when==='as_applicable'?'conditional':''} onClick={()=>setStage(s.stage)}><span className="pulse-seq">{String(i+1).padStart(2,'0')}</span><strong>{counts?.[s.stage] ?? '—'}</strong><span>{stageLabel(s.stage)}</span>{s.when==='as_applicable'&&<small>If applicable</small>}</button></li>)}</ol></div>{focus && <div className="pulse-inspector"><div><span className="eyebrow">INSPECTING / {stageLabel(focus.stage)}</span><p>{focus.stage===c.data.stage?'This case is here now.':'Prescribed route position; no completion inferred.'}</p></div><button className="secondary" onClick={()=>onNavigate?.('applications',{caseId:id})}>Inspect case →</button></div>}</>;
}

export function TrustTrace({records,selected,onSelect}) {
 const depth=useInstrumentDepth();
 return <section ref={depth} className="trust-trace" aria-label="Three independent assurance questions"><header><span className="eyebrow">TRUST & EVIDENCE</span><h2>Three checks. Distinct guarantees.</h2><p>Inspect a layer to read its evidence and limits.</p></header><div className="trust-architecture" aria-hidden="true">{records.slice(0,3).map((r,i)=><div key={r.id} className={`trust-slab slab-${i} ${selected===i ? "selected" : ""}`}><span>0{i+1}</span><strong>{r.label}</strong><i>{r.state}</i><svg viewBox="0 0 260 70"><path d={i===0?"M10 35H250":i===1?"M10 35H70V10H185V60H220V35H250":"M10 35H60L90 10H180L210 35H250"}/>{[10,60,130,200,250].map(x=><circle key={x} cx={x} cy="35" r="3"/>)}</svg></div>)}</div><div className="trust-lanes">{records.slice(0,3).map((r,i)=><button key={r.id} className={`trust-lane state-${r.state}`} aria-pressed={selected===i} onClick={()=>onSelect(i)}><span className="trace-index">0{i+1}</span><span><strong>{r.label}</strong><small>{r.detail}</small></span><svg viewBox="0 0 180 34" aria-hidden="true"><path d={i===0?'M5 17H175':i===1?'M5 17H65V5H115V29H145V17H175':'M5 17H45L65 5H125L145 17H175'}/><circle cx="5" cy="17" r="4"/><circle cx="175" cy="17" r="4"/></svg><span aria-hidden="true">↗</span></button>)}</div></section>
}
