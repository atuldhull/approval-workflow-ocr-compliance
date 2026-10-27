import World from '../operations/World.jsx';
import { Badge, Card, ErrorBox, Loading, useApi, when } from "../components/ui.jsx";

// How each line was measured. The badge colour then comes from what was FOUND (outcomeTone), so a check that ran
// and failed is never shown green.
const KIND = {
  VERIFIED_NOW: ["ok", "Checked now"],
  EVALUATED_ON_ANSWER_KEY: ["ok", "Evaluated on answer key"],
  MEASURED_ON_DEMO_TRAFFIC: ["warn", "Measured on synthetic demo traffic"],
  NOT_EVALUATED: ["neutral", "Not evaluated yet"],
};

function Result({ item }) {
  const r = item.result;
  if (!r) return <p className="muted">{item.note}</p>;
  if (item.key === "routing") {
    return (
      <>
        <p>
          {r.correct} of {r.cases} categories routed as expected ({Math.round(r.accuracy * 100)}%), ruleset {item.ruleset}.
        </p>
        {r.mismatches.length > 0 && (
          <ul>
            {r.mismatches.map((m) => (
              <li key={m.category}>
                {m.category}: expected {m.expected.join(" → ")}, got {m.got ? m.got.join(" → ") : "no route"}
              </li>
            ))}
          </ul>
        )}
      </>
    );
  }
  return <pre className="result">{JSON.stringify(r, null, 2)}</pre>;
}

export function outcomeTone(item) {
  const r = item.result;
  if (item.key === "ledger_integrity" && r) return !r.ok ? "bad" : r.assurance === "CHECKPOINTED" ? "ok" : "warn";
  if (item.key === "replay_consistency" && r) return r.verdict === "VERIFIED_COMPLETE" ? "ok" : r.verdict === "MISMATCH" ? "bad" : "warn";
  if (item.key === "routing" && r) return r.mismatches.length ? "warn" : "ok";
  return null;
}

export default function ScorecardView({ who }) {
  const { data, error, loading, reload } = useApi(who, "/analytics/scorecard");
  if (loading && !data) return <Loading what="Computing scorecard" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  return (
    <div>
      <World kind="scorecard" records={data.items.map(i=>({id:i.key,label:i.title,state:outcomeTone(i)||"unknown",detail:KIND[i.kind]?.[1]||i.kind,facts:[["Result",i.result?JSON.stringify(i.result):"Not evaluated"],["Evidence",i.source||i.note||"No source supplied"],["Ruleset",i.ruleset||"Not supplied"]]}))} />
      <p className="muted">
        Generated {when(data.generated_at)}. Each line says how it was measured; nothing is shown for parts not yet evaluated.
      </p>
      <div className="grid cards">
        {data.items.map((item) => {
          const [kindTone, label] = KIND[item.kind] ?? ["neutral", item.kind];
          const tone = outcomeTone(item) ?? kindTone;
          return (
            <Card key={item.key} title={item.title} className={`score tone-${tone}`}>
              <p>
                <Badge tone={tone}>{label}</Badge>
              </p>
              <Result item={item} />
              {item.source && <p className="source">Answer key: {item.source}</p>}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
