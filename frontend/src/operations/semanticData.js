import { stageLabel } from '../components/RouteJourney.jsx';
export const textState = value => String(value ?? 'Not supplied').replaceAll('_', ' ').toLowerCase();

// Route position is not proof that a prior stage was approved (conditional stages may be skipped).
export function routeRecords(app) {
  const at = app.route?.findIndex(r => r.stage === app.current_stage) ?? -1;
  return (app.route || []).map((r, i) => ({
    id: `${i}:${r.stage}`, label: stageLabel(r.stage),
    state: r.stage === app.current_stage ? 'active' : r.status || 'unknown',
    detail: r.status ? textState(r.status) : i === at ? 'Current stage' : at >= 0 && i < at ? 'Before current · completion not supplied' : 'Later in prescribed route',
    facts: [['Position', `${i + 1} of ${app.route.length}`], ['Applicability', r.when === 'as_applicable' ? 'If applicable' : r.when || 'Prescribed route'], ['Stage timestamp', r.completed_at || r.started_at || 'Not supplied'], ['Stage deadline', 'No stage-specific association supplied']],
  }));
}
export function applicationRecords(apps) {
  return (apps || []).map(a => ({ id: a.id, label: textState(a.category), state: a.status,
    detail: `${textState(a.status)} · ${a.current_stage ? textState(a.current_stage) : 'Not submitted'}`,
    stages: (a.route || []).map(r => ({label:stageLabel(r.stage), current:r.stage === a.current_stage})),
    facts: [['Case', a.id], ['Current stage', a.current_stage ? textState(a.current_stage) : 'Not submitted'], ['Academic year', a.academic_year || 'Not supplied']],
  }));
}
export function auditRecords(chain, verify, replay, checkpoints = []) {
  const bad=chain?.ok === false;
  // A checkpoint is "anchored" only with an intact chain and a witness the backend does not mark as same-machine demo.
  const demoWitness=String(verify?.witness_kind||'').includes('DEMO ONLY');
  const checkpointed=Boolean(verify?.ok && verify?.assurance?.startsWith('CHECKPOINTED'));
  const witnessState=bad||!checkpointed?'unknown':demoWitness?'recorded':'anchored';
  return [
    {id:'continuity',label:'Hash continuity',state:bad?'broken':chain?.ok?'checked':'unknown',detail:chain ? `${chain.checked ?? 0} entries checked · ${bad?'failed':'chain result: '+String(chain.ok)}`:'Not checked',facts:[['First broken sequence',chain?.first_bad_seq ?? 'None reported'],['Coverage','Continuity only; not independent anchoring'],['Event details','Full ledger events are not supplied by this endpoint']]},
    {id:'witness',label:'Checkpoint witness',state:witnessState,detail:verify ? `${verify.status} · ${verify.assurance}`:'Not checked',facts:[['Checkpoint coverage',verify?.checkpoint_seq ? `Through #${verify.checkpoint_seq}`:'No trusted sequence supplied'],['Newer entries',verify?.entries_after_checkpoint ?? 'Not supplied'],['Witness',verify?.witness_kind || 'Not configured'],['Independence',demoWitness?'Same machine (demo only); not independent':verify?.witness_kind?'As configured by the operator':'Not supplied'],['Coverage limit',bad?'Chain failure: no combined assurance claimed':'Checkpoint assurance is separate from replay'],['Scope','Integrity of this system\'s own log; not authentication by AICTE or any government system']]},
    {id:'replay',label:'Replay consistency',state:replay?.verdict==='MISMATCH'?'broken':replay?.verdict==='VERIFIED_COMPLETE'?'checked':'unknown',detail:replay?.verdict || 'Not run',facts:[['Gaps',replay ? String(replay.gaps?.length ?? 0) : 'Unknown until run'],['Meaning','Read-model consistency; not proof of independent anchoring']]},
    ...checkpoints.map((c,i)=>({id:`checkpoint-${c.id||i}`,label:`Checkpoint ${c.seq ?? c.sequence ?? i+1}`,state:c.status==='PENDING'?'pending':'recorded',detail:`Recorded checkpoint · ${c.status}`,facts:Object.entries(c).map(([k,v])=>[k,typeof v==='object'?JSON.stringify(v):String(v)])})),
  ];
}
export function datePositions(records) {
  const times=records.map(r=>Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(r.date)?r.date+"T00:00:00+05:30":r.date));const valid=times.filter(Number.isFinite);
  const min=Math.min(...valid), max=Math.max(...valid);
  return times.map(t=>Number.isFinite(t)?max===min?50:8+(t-min)/(max-min)*84:null);
}
