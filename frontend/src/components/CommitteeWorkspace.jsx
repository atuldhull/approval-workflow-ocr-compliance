import { useEffect, useState } from "react";
import { DEMO_USERS, api } from "../api.js";
import { useActionKey } from "../actionKey.js";
import { ROLE_LABELS, sentence } from "../nav.js";
import { COMMITTEE_TYPES, STAFFING, TASK_TITLES, refusal, taskLabel } from "../workflowText.js";
import { stageLabel } from "./RouteJourney.jsx";
import { Badge, ErrorBox, Loading, useSingleFlight, when } from "./ui.jsx";

// policy.py committee.create / task.assign / observation.add / report.add. Shown only to these roles; the server
// still checks the role and that the writer is a member of the committee.
const WRITERS = new Set(["SCRUTINY_COMMITTEE", "BUREAU_OFFICER"]);
const OFFICER_ROLES = new Set(["SCRUTINY_COMMITTEE", "RO_OFFICER", "BUREAU_OFFICER", "BUREAU_HEAD"]);

// Committees formed for a case are found from its audit timeline (wf.committee_formed carries the id); there is no
// per-case committee list endpoint yet.
export const committeeIdsFrom = (timeline) => [...new Set((timeline ?? [])
  .filter((e) => e.event_type === "wf.committee_formed" && e.payload?.committee_id).map((e) => e.payload.committee_id))];

function personName(ref, me, demo) {
  if (ref === me.user_id) return "you";
  const user = demo ? DEMO_USERS.find((u) => u.user === ref) : null;
  return user ? `${user.label} (demo)` : `user ${ref.slice(0, 8)}`;
}

// One POST with an Idempotency-Key per user action, reused when the same action is retried.
function useWrite(who, onDone) {
  const key = useActionKey();
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(null);
  const once = useSingleFlight();
  const send = (name, path, body) => once(async () => {
    setBusy(name);
    setFailure(null);
    try {
      await api(who, path, { method: "POST", body, headers: { "Idempotency-Key": key.for(`${path} ${JSON.stringify(body)}`) } });
      key.settle(null);
      onDone?.();
      return true;
    } catch (e) {
      key.settle(e);
      setFailure({ name, error: e });
      return false;
    } finally {
      setBusy(null);
    }
  });
  return { send, busy, failureFor: (name) => (failure?.name === name ? refusal(failure.error) : null) };
}

export default function CommitteeWorkspace({ who, me, caseRec, timeline, demo, onChanged }) {
  const ids = committeeIdsFrom(timeline);
  const [committees, setCommittees] = useState(null);
  const [reports, setReports] = useState({});
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const reload = () => setTick((t) => t + 1);
  const write = useWrite(who, () => { reload(); onChanged?.(caseRec.case_id); });

  useEffect(() => {
    let live = true;
    Promise.all(ids.map((id) => Promise.all([api(who, `/committees/${id}`), api(who, `/committees/${id}/reports`)])))
      .then((rows) => {
        if (!live) return;
        setCommittees(rows.map(([c]) => c));
        setReports(Object.fromEntries(rows.map(([c, r]) => [c.id, r])));
      })
      .catch((e) => live && setError(e));
    return () => { live = false; };
  }, [who, ids.join(","), tick]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!OFFICER_ROLES.has(me.role) && me.role !== "AUDITOR") return null;
  const canWrite = WRITERS.has(me.role);
  const staffing = STAFFING[caseRec.stage] ?? [];

  return (
    <section className="case-zone committees" aria-labelledby={`cm-${caseRec.case_id}`}>
      <h3 id={`cm-${caseRec.case_id}`}>Committee workspace</h3>
      <p className="muted small">
        {staffing.length
          ? `At ${stageLabel(caseRec.stage)} a member of an active ${staffing.map((t) => sentence(t)).join(" or ")} committee holds the assignment (demo assumption GF-001).`
          : "No committee staffs the case at its current stage."}{" "}
        Observations and reports are stored as protected notes; only their fingerprints are shown.
      </p>
      <ErrorBox error={refusal(error)} />
      {!committees && !error && <Loading what="Loading committees" rows={2} />}
      {committees?.length === 0 && <p className="muted">No committee has been formed for this case.</p>}
      {committees?.map((c) => (
        <Committee key={c.id} committee={c} reports={reports[c.id] ?? []} me={me} demo={demo}
          canWrite={canWrite && c.status === "ACTIVE" && c.members.some((m) => m.user_ref === me.user_id)} write={write} />
      ))}
      {canWrite && caseRec.status === "IN_PROCESS" && (
        <FormCommittee caseRec={caseRec} me={me} demo={demo} write={write} suggested={staffing[0] ?? "SCRUTINY"} />
      )}
    </section>
  );
}

function FormCommittee({ caseRec, me, demo, write, suggested }) {
  const [type, setType] = useState(suggested);
  const [others, setOthers] = useState([]);
  // Only demo accounts can be named as other members: there is no user directory to look people up in.
  const candidates = demo ? DEMO_USERS.filter((u) => WRITERS.has(u.role) && u.user !== me.user_id) : [];
  const submit = (e) => {
    e.preventDefault();
    write.send("form", `/cases/${caseRec.case_id}/committees`, {
      type, members: [{ user_ref: me.user_id, role: "CHAIR" }, ...others.map((u) => ({ user_ref: u, role: "MEMBER" }))],
    });
  };
  return (
    <form className="action-form" onSubmit={submit} aria-label="Form a committee">
      <h4>Form a committee</h4>
      <div className="form-grid">
        <label>
          Committee type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {COMMITTEE_TYPES.map((t) => <option key={t} value={t}>{sentence(t)}</option>)}
          </select>
        </label>
      </div>
      <fieldset>
        <legend>Members</legend>
        <p className="small">You, as chair.</p>
        {candidates.map((u) => (
          <label key={u.user} className="inline">
            <input type="checkbox" checked={others.includes(u.user)}
              onChange={(e) => setOthers((s) => (e.target.checked ? [...s, u.user] : s.filter((x) => x !== u.user)))} />
            {u.label} ({ROLE_LABELS[u.role]}, demo account)
          </label>
        ))}
      </fieldset>
      <ErrorBox error={write.failureFor("form")} />
      <div className="actions"><button disabled={Boolean(write.busy)}>{write.busy === "form" ? "Forming…" : "Form committee"}</button></div>
    </form>
  );
}

function Committee({ committee, reports, me, demo, canWrite, write }) {
  const [task, setTask] = useState({ title_key: TASK_TITLES[0][0], assignee_user_ref: me.user_id });
  const [observation, setObservation] = useState({});
  const [report, setReport] = useState("");
  const head = reports[reports.length - 1] ?? null;
  return (
    <article className="committee" aria-label={`${sentence(committee.type)} committee`}>
      <header className="round-head">
        <strong>{sentence(committee.type)} committee</strong>
        <Badge tone={committee.status === "ACTIVE" ? "ok" : "neutral"}>{sentence(committee.status)}</Badge>
        <span className="muted small">{committee.members.map((m) => `${personName(m.user_ref, me, demo)} (${sentence(m.role)})`).join(", ")}</span>
      </header>

      <h4>Tasks</h4>
      {committee.tasks.length === 0 && <p className="muted small">No tasks yet.</p>}
      <ul className="round-items">
        {committee.tasks.map((t) => (
          <li key={t.id} className="task">
            <span>{taskLabel(t.title_key)}</span>
            <span className="muted small">for {personName(t.assignee_user_ref, me, demo)} · {t.observations.length} observation{t.observations.length === 1 ? "" : "s"}</span>
            {canWrite && (
              <form className="inline-form" aria-label={`Add an observation to ${taskLabel(t.title_key)}`}
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (await write.send(`obs-${t.id}`, `/tasks/${t.id}/observations`, { body: observation[t.id] ?? "" })) setObservation((o) => ({ ...o, [t.id]: "" }));
                }}>
                <label>
                  <span className="sr-only">Observation</span>
                  <input value={observation[t.id] ?? ""} placeholder="Add an observation" autoComplete="off"
                    onChange={(e) => setObservation((o) => ({ ...o, [t.id]: e.target.value }))} />
                </label>
                <button className="small secondary" disabled={!(observation[t.id] ?? "").trim() || Boolean(write.busy)}>Add</button>
                <ErrorBox error={write.failureFor(`obs-${t.id}`)} />
              </form>
            )}
          </li>
        ))}
      </ul>
      {canWrite && (
        <form className="inline-form" aria-label="Assign a task" onSubmit={(e) => { e.preventDefault(); write.send(`task-${committee.id}`, `/committees/${committee.id}/tasks`, task); }}>
          <label>
            Task
            <select value={task.title_key} onChange={(e) => setTask((t) => ({ ...t, title_key: e.target.value }))}>
              {TASK_TITLES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </label>
          <label>
            Assign to
            <select value={task.assignee_user_ref} onChange={(e) => setTask((t) => ({ ...t, assignee_user_ref: e.target.value }))}>
              {committee.members.map((m) => <option key={m.user_ref} value={m.user_ref}>{personName(m.user_ref, me, demo)}</option>)}
            </select>
          </label>
          <button className="small secondary" disabled={Boolean(write.busy)}>Assign task</button>
          <ErrorBox error={write.failureFor(`task-${committee.id}`)} />
        </form>
      )}

      <h4>Report versions</h4>
      {reports.length === 0 && <p className="muted small">No report yet.</p>}
      <ol className="round-items reports">
        {reports.map((r) => (
          <li key={r.id}>
            <span>Version {r.version_no}</span>
            <span className="muted small">by {personName(r.author_user_ref, me, demo)} · {when(r.created_at)} · fingerprint <code>{r.content_note_hash.slice(0, 12)}</code>
              {r.diff.comparison === "HASH_ONLY" ? (r.diff.content_changed ? " · changed from the previous version" : " · same text as the previous version") : " · first version"}</span>
          </li>
        ))}
      </ol>
      {canWrite && (
        <form className="action-form" aria-label="Add a report version" onSubmit={async (e) => {
          e.preventDefault();
          // parent_version names the version written on top of, so a concurrent addition is refused, not overwritten
          if (await write.send(`report-${committee.id}`, `/committees/${committee.id}/reports`, { content: report, parent_version: head?.id ?? null })) setReport("");
        }}>
          <label>
            {head ? `New version on top of version ${head.version_no}` : "First report version"}
            <textarea rows={3} value={report} onChange={(e) => setReport(e.target.value)} />
          </label>
          <ErrorBox error={write.failureFor(`report-${committee.id}`)} />
          <div className="actions"><button className="small" disabled={!report.trim() || Boolean(write.busy)}>Add report version</button></div>
        </form>
      )}
    </article>
  );
}
