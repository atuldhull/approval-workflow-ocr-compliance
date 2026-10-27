// How a deadline turns into something a person sees, in the order the system records it. Each screen that shows a
// part of this chain shows the whole chain with its own part marked, so a reader knows where the other parts live.
// It is an explanation of the pipeline, not a status display: nothing here changes with the data.
const STEPS = [
  ["deadline", "Deadline falls due", "Deadline service, on its rule's date"],
  ["alerts", "Alert level raised", "Alerts: addressed to one role"],
  ["delivery", "Message sent per channel", "Alert delivery: attempts, retries, dead letters"],
  ["inbox", "Notice in the inbox", "Inbox: read or unread"],
  ["ack", "Acknowledged", "Alerts: by the addressed role; stops escalation"],
];

export default function Lifecycle({ here }) {
  const marks = Array.isArray(here) ? here : [here];
  return (
    <ol className="lifecycle" aria-label="From deadline to acknowledgement">
      {STEPS.map(([key, title, where]) => (
        <li key={key} className={marks.includes(key) ? "is-here" : undefined} aria-current={marks.includes(key) ? "step" : undefined}>
          <span className="lc-title">{title}</span>
          <span className="lc-where">{where}</span>
        </li>
      ))}
    </ol>
  );
}
