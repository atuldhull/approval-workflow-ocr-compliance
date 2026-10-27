import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { Workspace } from '../App.jsx';
import World from '../operations/World.jsx';
import { DEMO_USERS } from '../api.js';
import { fakeServer } from './fakeServer.js';
import ApplicationsView from '../views/ApplicationsView.jsx';
const who=DEMO_USERS[0], me={user_id:who.user,role:who.role,institution_id:who.institution};
afterEach(()=>history.replaceState(null,'','/'));

it('keeps record selection and case opening usable without WebGL',async()=>{
  const open=vi.fn();const user=userEvent.setup();
  render(<World kind="overview" records={[{id:'one',label:'Case one',detail:'Draft'},{id:'two',label:'Case two',detail:'In process'}]} onSelect={open}/>);
  expect(screen.getByText('Labelled evidence view')).toBeVisible();
  await user.click(within(screen.getByRole('group',{name:'Institution workflow records'})).getByRole('button',{name:/Case two/}));
  await user.click(screen.getByRole('button',{name:/Open selected case/}));expect(open).toHaveBeenCalledWith('two');
});

it('remembers the standard-view preference and provides readable empty state',async()=>{
  const user=userEvent.setup();render(<World kind="audit" records={[]}/>);
  expect(screen.getByText('No records to explore')).toBeVisible();
  await user.click(screen.getByRole('button',{name:'Standard view'}));
  expect(localStorage.getItem('operations.flat')).toBe('true');expect(screen.getByRole('button',{name:'Spatial view'})).toBeVisible();
});

it('opens an allowed deep link and restores browser navigation without losing the shell',async()=>{
  fakeServer({'GET /api/applications':[],'GET /api/notifications/inbox':[]});history.replaceState(null,'','#inbox');
  render(<Workspace who={who} me={me} config={{mode:'demo'}}/>);
  expect(screen.getByRole('heading',{level:1})).toHaveTextContent('Inbox');
  history.replaceState(null,'','#overview');window.dispatchEvent(new PopStateEvent('popstate'));
  await waitFor(()=>expect(screen.getByRole('heading',{level:1})).toHaveTextContent('Overview'));
});

it('never renders a privileged world from an institution deep link',async()=>{
  const calls=fakeServer({'GET /api/applications':[]});history.replaceState(null,'','#audit');
  render(<Workspace who={who} me={me} config={{mode:'demo'}}/>);
  expect(screen.getByRole('heading',{level:1})).toHaveTextContent('Overview');
  expect(calls.some(c=>c.url.includes('/audit'))).toBe(false);
});

it('puts a newly created case in the address so a refresh reopens it',async()=>{
  const draft={id:'new-1',status:'DRAFT',category:'NEW_PROGRAMME',academic_year:'2027-28',route:null,current_stage:null};
  fakeServer({'GET /api/applications':[],'GET /api/rulesets/aph-2024-27@r1':{routes:[{category:'NEW_PROGRAMME',label:'New programme',stages:[]}]},
    'POST /api/applications':()=>Promise.resolve([201,draft]),'GET /api/applications/new-1':draft,'GET /api/deadlines':[],'GET /api/cases/new-1/timeline':[]});
  history.replaceState(null,'','#applications');const user=userEvent.setup();
  render(<ApplicationsView who={who} me={me}/>);
  await screen.findByRole('option',{name:'New programme'});
  await user.click(screen.getByRole('button',{name:'Create draft'}));
  await waitFor(()=>expect(window.location.hash).toBe('#applications?case=new-1'));
});
