import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import RouteJourney from '../components/RouteJourney.jsx';
import OperationsPulse, { TrustTrace } from '../product/Instruments.jsx';
import { fakeServer } from './fakeServer.js';
import { DEMO_USERS } from '../api.js';
const who=DEMO_USERS.find(u=>u.key==='ro-southern');
it('route selection is reversible inspection and does not invent completion or mutate',async()=>{
 const calls=fakeServer({});render(<RouteJourney route={[{stage:'SCRUTINY'},{stage:'EVC',when:'as_applicable'}]} current="SCRUTINY" status="IN_PROCESS"/>);
 const u=userEvent.setup();await u.click(screen.getByRole('button',{name:'Inspect Expert visit, stage 2'}));expect(screen.getByText('Conditional · only if applicable')).toBeInTheDocument();await u.click(screen.getByRole('button',{name:'Inspect Scrutiny, stage 1'}));expect(screen.getByText('Current recorded position')).toBeInTheDocument();expect(calls).toHaveLength(0);
});
it('pulse uses the regional case endpoint, actual route and no fabricated zero',async()=>{
 const calls=fakeServer({'GET /api/cases':{items:[{case_id:'c1',route_id:'TEST',status:'IN_PROCESS',stage:'SCRUTINY'}]},'GET /api/cases/c1':{stage:'SCRUTINY',route:[{stage:'SCRUTINY'},{stage:'EVC',when:'as_applicable'}]},'GET /api/alerts':[]});
 const navigate=vi.fn();render(<OperationsPulse who={who} me={{role:'RO_OFFICER',region:'Southern'}} counts={{SCRUTINY:7}} onNavigate={navigate}/>);
 expect(await screen.findByText('7')).toBeInTheDocument();expect(screen.getByText('—')).toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'Inspect case →'}));expect(navigate).toHaveBeenCalledWith('applications',{caseId:'c1'});expect(calls.some(c=>c.url.includes('/cases?region=Southern&limit=100'))).toBe(true);expect(calls.some(c=>c.url==='/api/applications')).toBe(false);expect(calls.every(c=>c.method==='GET')).toBe(true);
});
it('trust layer selection never implies an assurance result or runs a check',async()=>{
 const select=vi.fn(),calls=fakeServer({});render(<TrustTrace records={[{id:'a',label:'Continuity',state:'checked',detail:'Intact'},{id:'b',label:'Witness',state:'unknown',detail:'Not anchored'},{id:'c',label:'Replay',state:'unknown',detail:'Not run'}]} selected={0} onSelect={select}/>);await userEvent.click(screen.getByRole('button',{name:/Witness/}));expect(select).toHaveBeenCalledWith(1);expect(screen.getByText('Not run')).toBeInTheDocument();expect(calls).toHaveLength(0);
});
