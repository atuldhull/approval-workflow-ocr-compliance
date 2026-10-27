import World from '../operations/World.jsx';
import { Badge, Card, PreviewBanner } from "../components/ui.jsx";
import { EVC_SAMPLE } from "../fixtures/previews.js";

export function EvcView() {
  return (
    <div>
      <PreviewBanner owner="Person 1" api="EVC scheduling API" />
      <World kind="evc" preview records={EVC_SAMPLE.map(r=>({id:r.request,label:r.institution,date:r.slot.replace(" ","T")+":00+05:30",dateLabel:r.slot+" IST",state:"sample",detail:r.slot+" · "+r.experts+" experts · SAMPLE",facts:[["Request",r.request],["Conflicts",r.conflicts],["Status","Sample candidate · not confirmed"],["Participants",r.experts+" experts; identities not supplied"]]}))} />
      <Card title="Proposed EVC slots (sample)">
        <table className="table" tabIndex={0}>
          <thead>
            <tr>
              <th scope="col">Request</th>
              <th scope="col">Institution</th>
              <th scope="col">Proposed slot</th>
              <th scope="col">Experts</th>
              <th scope="col">Conflicts</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {EVC_SAMPLE.map((r) => (
              <tr key={r.request}>
                <td>{r.request}</td>
                <td>{r.institution}</td>
                <td>{r.slot}</td>
                <td>{r.experts}</td>
                <td>{r.conflicts ? <Badge tone="warn">{r.conflicts} conflict</Badge> : <Badge tone="ok">none</Badge>}</td>
                <td>
                  <button className="small" disabled title="Needs the EVC scheduling API from Person 1">
                    Approve slot
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

