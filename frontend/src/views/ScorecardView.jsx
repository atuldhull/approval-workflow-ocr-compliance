import { Badge, Card, ErrorBox, Loading, useApi, when } from "../components/ui.jsx";

const KIND = {
  VERIFIED_NOW: ["ok", "Verified now"],
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

export default function ScorecardView({ who }) {
  const { data, error, loading } = useApi(who, "/analytics/scorecard");
  if (loading && !data) return <Loading what="Computing scorecard" />;
  if (error) return <ErrorBox error={error} />;
  return (
    <div>
      <p className="muted">
        Generated {when(data.generated_at)}. Each line says how it was measured; nothing is shown for parts not yet evaluated.
      </p>
      <div className="grid cards">
        {data.items.map((item) => {
          const [tone, label] = KIND[item.kind] ?? ["neutral", item.kind];
          return (
            <Card key={item.key} title={item.title}>
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
