import { Badge, Card, PreviewBanner } from "../components/ui.jsx";
import { EVC_SAMPLE, OBLIGATION_SAMPLE } from "../fixtures/previews.js";

export function EvcView() {
  return (
    <div>
      <PreviewBanner owner="Person 1" api="EVC scheduling API" />
      <Card title="Proposed EVC slots (sample)">
        <table className="table">
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

export function ComplianceView() {
  return (
    <div>
      <PreviewBanner owner="Person 2" api="obligations and evidence API" />
      <Card title="Compliance items (sample)">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Kind</th>
              <th scope="col">Item</th>
              <th scope="col">Due</th>
              <th scope="col">Evidence</th>
              <th scope="col">State</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {OBLIGATION_SAMPLE.map((o) => (
              <tr key={o.title}>
                <td>{o.kind}</td>
                <td>{o.title}</td>
                <td>{o.due}</td>
                <td>{o.evidence ?? "—"}</td>
                <td>{o.state.replaceAll("_", " ")}</td>
                <td>
                  <button className="small" disabled title="Needs the evidence review API from Person 2">
                    Review evidence
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
