"""Scorecard: what the system can show about its own correctness, labelled by how it was measured.

Every item keeps the method apart from the result:
- kind     how it was measured (below), and `method`, one sentence saying exactly what was checked;
- result   the numbers found (None when nothing was measured);
- outcome  PASS, ATTENTION or FAIL when the check has a verdict; None for a plain measurement;
- finding  the result in one plain sentence; `note` says why an item was not evaluated.

Kinds:
- VERIFIED_NOW: an invariant checked over every live record at request time (ledger, replay, scanning, four-eyes).
- MEASURED_ON_DEMO_TRAFFIC: real measurements, but of synthetic demo activity (delivery, alert timeliness, OCR).
- EVALUATED_ON_ANSWER_KEY: compared with an answer-key fixture in ANSWER_KEYS_DIR.
- NOT_EVALUATED: no answer key or no data yet. No number is shown.

Answer keys (JSON) in ANSWER_KEYS_DIR (default generator/answer_keys):
- routing.json  {"source": "...", "cases": [{"category": "NEW_PROGRAMME", "expected_stages": ["SCRUTINY", ...]}]}
- ocr.json      {"source": "...", "cases": [{"id": "...", "field": "...", "expected": "...", "predicted": "..."}]}

The document, compliance and deadline checks only read those modules' tables; nothing here changes them.
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.compliance.models import ApprovalLetter, Evidence
from app.deadlines.alerts import alert_config
from app.deadlines.models import Alert, Deadline
from app.documents.models import DocumentVersion, Fact, OcrRun
from app.platform import audit, notifier, replay
from app.platform.db import new_session
from app.platform.registry import port
from app.platform.settings import REPO_ROOT
from contracts.enums import DeadlineStatus, FactState
from contracts.errors import ContractError
from contracts.ports import ClockPort, RulesetPort

PASS, ATTENTION, FAIL = "PASS", "ATTENTION", "FAIL"
# the timer worker polls about once a minute; a level counts as missed only once it is this far overdue
ALERT_GRACE = timedelta(minutes=15)
# a version still waiting for its malware scan after this long means the scanner is not answering
SCAN_STALE = timedelta(minutes=30)


def answer_keys_dir() -> Path:
    return Path(os.environ.get("ANSWER_KEYS_DIR", REPO_ROOT / "generator" / "answer_keys"))


def _load(name: str) -> dict | None:
    path = answer_keys_dir() / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _item(key: str, title: str, kind: str, method: str, result: dict | None = None, outcome: str | None = None,
          finding: str | None = None, note: str | None = None, **extra) -> dict:
    return {"key": key, "title": title, "kind": kind, "method": method, "result": result, "outcome": outcome,
            "finding": finding, "note": note, **extra}


def _not_evaluated(key: str, title: str, method: str, note: str) -> dict:
    return _item(key, title, "NOT_EVALUATED", method, note=note)


# ---- ledger and replay ----

def _ledger(session) -> dict:
    v = audit.verify(session, audit.configured_trusted_keys(), audit.configured_witness())
    outcome = FAIL if not v.ok else PASS if v.assurance == "CHECKPOINTED" else ATTENTION
    finding = (f"{v.checked} entries checked: {v.status}." if not v.ok else
               f"All {v.checked} entries chain correctly" + (
                   ", and the newest signed checkpoint matches the witness." if v.assurance == "CHECKPOINTED" else
                   "; no signed checkpoint covers them yet, so a full rewrite would not be detected."))
    return _item("ledger_integrity", "Ledger integrity", "VERIFIED_NOW",
                 "Recomputes every entry's hash chain and checks signed checkpoints against the independent witness.",
                 {"status": v.status, "ok": v.ok, "assurance": v.assurance, "entries_checked": v.checked},
                 outcome, finding)


def _replay() -> dict:
    rep = replay.replay()
    outcome = PASS if rep["verdict"] == "VERIFIED_COMPLETE" else FAIL if rep["verdict"] == "MISMATCH" else ATTENTION
    return _item("replay_consistency", "Read models vs events (replay)", "VERIFIED_NOW",
                 "Rebuilds the read models from the event log alone and compares them with the live tables.",
                 {"ok": rep["ok"], "verdict": rep["verdict"], "gaps": len(rep["gaps"]),
                  "projections": {p["name"]: p["status"] for p in rep["projections"]},
                  "unhandled_event_types": rep["unhandled_event_types"]},
                 outcome, f"Replay verdict {rep['verdict']} with {len(rep['gaps'])} gap(s).")


# ---- alert delivery (notifier ledger) ----

def _delivery(now: datetime) -> dict:
    key, title = "delivery_reliability", "Alert delivery (last 24 hours)"
    method = ("Reads the notifier's delivery-attempt ledger: each message's first try in the last 24 hours, "
              "messages delivered only after a retry, and dead letters.")
    health = notifier.health(now)
    attempts = sum(health["attempts_24h"].values())
    if not attempts:
        return _not_evaluated(key, title, method, "No delivery attempts in the last 24 hours.")
    rate, dead = health["first_try_success_rate_24h"], health["by_status"]["DEAD"]
    stuck = health["stalled_sending"]
    outcome = ATTENTION if dead or stuck or (rate is not None and rate < 0.95) else PASS
    rate_text = f"{round(rate * 100)}% delivered on the first try" if rate is not None else "no first tries"
    return _item(key, title, "MEASURED_ON_DEMO_TRAFFIC", method,
                 {"attempts": attempts, "first_tries": health["first_tries_24h"], "first_try_success_rate": rate,
                  "delivered_after_retry": health["delivered_after_retry_24h"], "dead_letters": dead,
                  "stalled_sending": stuck},
                 outcome, f"{attempts} attempt(s): {rate_text}, {dead} dead letter(s), {stuck} stalled.")


# ---- alert timeliness (deadline tables) ----

def _due_levels(d: Deadline, ladder, config, raised: dict[int, Alert], cutoff: datetime) -> list[tuple[int, datetime]]:
    """The ladder levels that should exist by now for the deadline's current due_version, with when each fell due.
    A level after a vacant one is due at once (the vacancy rule); levels stop where the ladder is not yet due.
    cutoff is the instant by which a level must exist (now less the worker's grace, or the acknowledgement)."""
    due, previous = [], None
    for step in ladder:
        fire_at = config.fire_at(step, d.due_at)
        if previous is not None and previous.status == "VACANT":
            fire_at = min(fire_at, previous.raised_at)
        if fire_at > cutoff:
            break
        due.append((step.level, fire_at))
        previous = raised.get(step.level)
        if previous is None:
            break   # the chain stops at the first missing level; later levels depend on it
    return due


def _alert_timeliness(session, now: datetime) -> dict:
    key, title = "alerts", "Deadline alerts raised when due (missed / duplicate / early)"
    method = ("For every running deadline, works out from its alert ladder which levels have fallen due "
              f"(allowing {int(ALERT_GRACE.total_seconds() // 60)} minutes for the timer worker) and compares them "
              "with "
              "the alerts actually raised for the current due date. Acknowledged deadlines stop their ladder.")
    alerts = session.scalars(select(Alert)).all()
    by_deadline: dict = defaultdict(list)
    for a in alerts:
        by_deadline[a.deadline_id].append(a)
    duplicates = sum(n - 1 for n in Counter((a.deadline_id, a.level, a.due_version) for a in alerts).values() if n > 1)

    expected = on_time = missed = early = 0
    lag_hours: list[float] = []
    missed_by_subject: Counter = Counter()
    for d in session.scalars(select(Deadline).where(Deadline.status == DeadlineStatus.RUNNING)).all():
        current = {a.level: a for a in by_deadline.get(d.id, ()) if a.due_version == d.due_version}
        acked = [a.acknowledged_at for a in current.values() if a.status == "ACKNOWLEDGED" and a.acknowledged_at]
        # an acknowledgement stops the ladder: only levels that fell due before it should exist
        until = min(acked) if acked else now - ALERT_GRACE
        try:
            config, ladder = alert_config(d)
        except ContractError:
            continue
        if not ladder:
            continue
        for level, fire_at in _due_levels(d, ladder, config, current, until):
            expected += 1
            a = current.get(level)
            if a is None:
                missed += 1
                missed_by_subject[d.subject_type] += 1
                continue
            on_time += 1
            lag_hours.append(round((a.raised_at - fire_at).total_seconds() / 3600, 2))
        for level, a in current.items():
            step = next((s for s in ladder if s.level == level), None)
            if step is not None and level == 0 and a.raised_at < config.fire_at(step, d.due_at):
                early += 1   # level 0 has no vacancy shortcut, so it must never be raised before its offset

    if not expected and not alerts:
        return _not_evaluated(key, title, method, "No alert level has fallen due yet (try time travel and the timers).")
    outcome = FAIL if missed or duplicates or early else PASS
    finding = (f"{on_time} of {expected} due level(s) raised; {missed} missed, {duplicates} duplicate(s), "
               f"{early} early.")
    if missed_by_subject:
        finding += " Missed by subject: " + ", ".join(f"{k} {v}" for k, v in sorted(missed_by_subject.items())) + "."
    return _item(key, title, "MEASURED_ON_DEMO_TRAFFIC", method,
                 {"levels_due": expected, "raised": on_time, "missed": missed, "duplicates": duplicates,
                  "early": early, "alerts_total": len(alerts), "missed_by_subject_type": dict(missed_by_subject),
                  # time travel jumps the clock, so a lag here is usually the jump, not a slow worker
                  "max_lag_hours": max(lag_hours) if lag_hours else None},
                 outcome, finding)


# ---- documents: scanning and four-eyes ----

def _scanning(session, now: datetime) -> dict:
    key, title = "document_scanning", "Document malware scanning"
    method = ("Counts document versions by scan verdict, and checks that no version that is not scanned clean "
              "was ever used: text extraction, compliance evidence or an approval letter. There is no download "
              "endpoint, so these are the only ways a file's contents are served.")
    counts = dict(session.execute(select(DocumentVersion.scan_status, func.count())
                                  .group_by(DocumentVersion.scan_status)).all())
    total = sum(counts.values())
    if not total:
        return _not_evaluated(key, title, method, "No documents have been uploaded yet.")
    not_clean = DocumentVersion.scan_status != "clean"
    used = {
        "extractions": session.scalar(select(func.count()).select_from(OcrRun).join(
            DocumentVersion, DocumentVersion.document_version_id == OcrRun.document_version_id).where(not_clean)),
        "evidence": session.scalar(select(func.count()).select_from(Evidence).join(
            DocumentVersion, DocumentVersion.document_version_id == Evidence.document_version_id).where(not_clean)),
        "letters": session.scalar(select(func.count()).select_from(ApprovalLetter).join(
            DocumentVersion, DocumentVersion.document_version_id == ApprovalLetter.document_version_id)
            .where(not_clean)),
    }
    oldest = session.scalar(select(func.min(DocumentVersion.created_at))
                            .where(DocumentVersion.scan_status == "scan_pending"))
    stale = oldest is not None and now - oldest > SCAN_STALE
    misused = sum(used.values())
    outcome = FAIL if misused else ATTENTION if stale else PASS
    pending = counts.get("scan_pending", 0)
    finding = (f"{total} version(s): {counts.get('clean', 0)} clean, {counts.get('infected', 0)} infected, "
               f"{pending} waiting for a scan. "
               + (f"{misused} use(s) of a version that was not scanned clean." if misused else
                  "No version was used before it was scanned clean.")
               + (" A version has waited more than 30 minutes: is the scanner running?" if stale else ""))
    return _item(key, title, "VERIFIED_NOW", method,
                 {"versions": total, "clean": counts.get("clean", 0), "infected": counts.get("infected", 0),
                  "scan_pending": pending,
                  "oldest_pending_minutes": int((now - oldest).total_seconds() // 60) if oldest else None,
                  "used_while_not_clean": used},
                 outcome, finding)


def _four_eyes(session) -> dict:
    key, title = "four_eyes", "Four-eyes on extracted facts and evidence"
    method = ("Checks every confirmed fact: it was reviewed first, and confirmed by a different officer from the one "
              "who typed and reviewed it (the database also refuses such a row). Checks every evidence decision was "
              "taken by a human role.")
    confirmed = session.scalars(select(Fact).where(Fact.confirmed_at.is_not(None))).all()
    decided = session.scalar(select(func.count()).select_from(Evidence).where(Evidence.verified_at.is_not(None)))
    if not confirmed and not decided:
        return _not_evaluated(key, title, method, "No fact has been confirmed and no evidence decided yet.")
    own = sum(1 for f in confirmed if f.confirmed_by is not None and f.confirmed_by == f.review_typed_by)
    unreviewed = sum(1 for f in confirmed if f.reviewed_at is None
                     or f.state not in (FactState.CONFIRMED.value, FactState.CORRECTED.value))
    automated = session.scalar(select(func.count()).select_from(Evidence).where(Evidence.verified_role == "SYSTEM"))
    outcome = FAIL if own or unreviewed or automated else PASS
    finding = (f"{len(confirmed)} confirmed fact(s): {own} confirmed by their own reviewer, {unreviewed} without a "
               f"review. {decided} evidence decision(s), {automated} by an automated actor.")
    return _item(key, title, "VERIFIED_NOW", method,
                 {"confirmed_facts": len(confirmed), "confirmed_by_own_reviewer": own,
                  "confirmed_without_review": unreviewed, "evidence_decisions": decided,
                  "evidence_decided_by_system": automated},
                 outcome, finding)


# ---- OCR and routing ----

def _routing() -> dict:
    key, title = "routing", "Workflow routing vs APH Table 2.3"
    method = ("Compares the stages the active ruleset gives each Table 2.3 category with an independent "
              "answer key (routing.json).")
    answer = _load("routing.json")
    if answer is None:
        return _not_evaluated(key, title, method,
                              "Needs the workflow owner's answer key (routing.json, expected stages per category). "
                              "Checking the ruleset against itself would prove nothing, so no number is shown.")
    rules = port(RulesetPort)
    ruleset = rules.default_key()
    mismatches = []
    for case in answer["cases"]:
        try:
            got = [str(s.stage) for s in rules.route_for(case["category"], ruleset).stages]
        except ContractError:
            got = None
        if got != case["expected_stages"]:
            mismatches.append({"category": case["category"], "expected": case["expected_stages"], "got": got})
    n = len(answer["cases"])
    return _item(key, title, "EVALUATED_ON_ANSWER_KEY", method,
                 {"cases": n, "correct": n - len(mismatches),
                  "accuracy": round((n - len(mismatches)) / n, 3) if n else None, "mismatches": mismatches},
                 ATTENTION if mismatches else PASS, f"{n - len(mismatches)} of {n} categories routed as expected.",
                 source=answer.get("source"), ruleset=ruleset)


def _ocr(session) -> dict:
    key, title = "ocr", "OCR field extraction"
    answer = _load("ocr.json")
    if answer is not None:
        per_field: dict[str, list[bool]] = defaultdict(list)
        for case in answer["cases"]:
            per_field[case["field"]].append(case.get("predicted") == case["expected"])
        return _item(key, title, "EVALUATED_ON_ANSWER_KEY",
                     "Exact match of predicted values with the expected values in the answer key (ocr.json).",
                     {f: {"cases": len(v), "exact_match": round(sum(v) / len(v), 3)} for f, v in per_field.items()},
                     source=answer.get("source"))
    method = ("Uses the officers' blind entries as ground truth: each reviewer types the value before seeing the "
              "OCR suggestion, so agreement between the two measures the text engine. Also counts review decisions.")
    reviewed = session.scalars(select(Fact).where(Fact.reviewed_at.is_not(None))).all()
    if not reviewed:
        return _not_evaluated(key, title, method, "No extracted fact has been reviewed by an officer yet.")
    decisions = Counter(f.state for f in reviewed)
    comparable = [f for f in reviewed if f.normalized_value is not None and f.review_typed_value is not None]
    agree = sum(1 for f in comparable if f.review_typed_value.strip() == f.normalized_value)
    per_field: dict[str, list[bool]] = defaultdict(list)
    for f in comparable:
        per_field[f.field_key].append(f.review_typed_value.strip() == f.normalized_value)
    rate = round(agree / len(comparable), 3) if comparable else None
    finding = (f"{len(reviewed)} reviewed fact(s): {decisions.get(FactState.CONFIRMED.value, 0)} accepted, "
               f"{decisions.get(FactState.CORRECTED.value, 0)} corrected, {decisions.get(FactState.REJECTED.value, 0)} "
               f"rejected. " + (f"Blind entry matched the OCR value {agree} of {len(comparable)} times."
                                if comparable else "No reviewed fact had a normalised OCR value to compare."))
    return _item(key, title, "MEASURED_ON_DEMO_TRAFFIC", method,
                 {"reviewed": len(reviewed), "accepted": decisions.get(FactState.CONFIRMED.value, 0),
                  "corrected": decisions.get(FactState.CORRECTED.value, 0),
                  "rejected": decisions.get(FactState.REJECTED.value, 0),
                  "blind_entry_agreement": rate,
                  "by_field": {k: {"cases": len(v), "agreement": round(sum(v) / len(v), 3)}
                               for k, v in sorted(per_field.items())}},
                 None, finding)


def scorecard() -> dict:
    now = port(ClockPort).now()
    with new_session() as s:
        ledger = _ledger(s)
        rows = [_scanning(s, now), _four_eyes(s), _alert_timeliness(s, now), _ocr(s)]
    return {"generated_at": now.isoformat(), "items": [
        ledger, _replay(), _delivery(now), rows[2], rows[0], rows[1], rows[3], _routing(),
    ]}
