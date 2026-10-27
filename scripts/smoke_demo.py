"""Demo-day smoke test against a running stack with demo sign-in. Synthetic data only.

    docker compose --profile worker --profile scanning up -d    # default stack (DEMO_AUTH=true) + ClamAV
    python scripts/smoke_demo.py --docker                       # also delivers alerts inside the backend container

Checks what the UI shows, over HTTP:
- a draft refused until its mandatory checklist items are linked to clean documents, then submitted and shown in the
  case list, its deadline and explanation, the audit timeline and replay, dashboard;
- documents: a synthetic PDF uploaded with an Idempotency-Key (and replayed), the malware scan, text extraction,
  blind entry before the OCR suggestion is revealed, review, the four-eyes refusal and a second officer's confirmation;
- compliance: the bureau registers an LoA from the confirmed issue-date fact, the institution submits evidence and an
  officer verifies it;
- time travel, a timer run, and the regional officer acknowledging the alert it raised;
- security headers on API responses, and the scorecard evaluating what was just done.

Run it against a stack you can throw away: time travel moves the shared demo clock forward for good.
Without ClamAV the upload stays scan_pending, and every check after it is reported as failed.
Real sign-in with Keycloak and Cerbos is covered separately by scripts/smoke_security.py.
"""
import argparse
import shlex
import subprocess
import sys
import time
import uuid

import httpx

SUNRISE = "00000000-0000-4000-8000-000000000001"
U = lambda n: f"00000000-0000-4000-9000-{n:012d}"  # noqa: E731
INST = {"X-Demo-User": U(1), "X-Demo-Role": "INSTITUTION", "X-Demo-Institution": SUNRISE}
HEAD = {"X-Demo-User": U(7), "X-Demo-Role": "BUREAU_HEAD"}
BUREAU = {"X-Demo-User": U(6), "X-Demo-Role": "BUREAU_OFFICER"}
SCRUTINY = {"X-Demo-User": U(2), "X-Demo-Role": "SCRUTINY_COMMITTEE"}
RO_SOUTH = {"X-Demo-User": U(5), "X-Demo-Role": "RO_OFFICER", "X-Demo-Region": "Southern"}
API_HEADERS = {
    "x-content-type-options": "nosniff", "x-frame-options": "DENY", "referrer-policy": "no-referrer",
    "cross-origin-resource-policy": "same-origin", "cache-control": "no-store",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
}

results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f': {detail}' if detail else ''}")
    return bool(ok)


def synthetic_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a real text layer (Helvetica), built by hand so the script needs only httpx."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    text = " T* ".join(f"({esc(line)}) Tj" for line in lines)
    stream = f"BT /F1 12 Tf 16 TL 72 760 Td {text} ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> "
        b"/Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def upload(api: httpx.Client, app_id: str, doc_type: str, content: bytes, key: str, name: str) -> httpx.Response:
    return api.post(f"/applications/{app_id}/documents", headers={**INST, "Idempotency-Key": key},
                    data={"doc_type": doc_type}, files={"file": (name, content, "application/pdf")})


def wait_for_scan(api: httpx.Client, app_id: str, version_id: str, timeout: float) -> str:
    """Polls the case's documents until the version's scan has a verdict (the scan runs after the upload)."""
    deadline, status = time.monotonic() + timeout, "missing"
    while time.monotonic() < deadline:
        for doc in api.get(f"/applications/{app_id}/documents", headers=INST).json():
            for v in doc["versions"]:
                if v["version_id"] == version_id:
                    status = v["scan_status"]
        if status != "scan_pending":
            return status
        # the background scan may have hit an unavailable scanner; ask for a rescan (the uploader's action)
        api.post(f"/document-versions/{version_id}/scan", headers=INST)
        time.sleep(3)
    return status


def headers_ok(response: httpx.Response) -> list[str]:
    return [k for k, v in API_HEADERS.items() if response.headers.get(k) != v]


def documents_and_review(api: httpx.Client, app_id: str, a) -> dict | None:
    run_id = uuid.uuid4().hex[:8]
    pdf = synthetic_pdf(["SYNTHETIC DEMO LETTER - NOT A REAL AICTE DOCUMENT",
                         "letter_issue_date: 2025-03-12", f"letter_file_number: F.No.DEMO/{run_id}"])
    key = f"smoke-upload-{run_id}"
    first = upload(api, app_id, "LOA_LETTER", pdf, key, "loa-demo.pdf")
    if not check("document uploaded with an Idempotency-Key", first.status_code == 201, str(first.status_code)):
        print("      ", first.text[:300])
        return None
    check("upload response carries the API security headers", not headers_ok(first), ", ".join(headers_ok(first)))
    again = upload(api, app_id, "LOA_LETTER", pdf, key, "loa-demo.pdf")
    check("retrying the same upload replays the first answer",
          again.status_code == 201 and again.json() == first.json() and again.headers.get("idempotent-replayed") == "true",
          f"{again.status_code}, replayed={again.headers.get('idempotent-replayed')}")
    no_key = api.post(f"/applications/{app_id}/documents", headers=INST, data={"doc_type": "LOA_LETTER"},
                      files={"file": ("x.pdf", pdf, "application/pdf")})
    check("an upload without an Idempotency-Key is refused", no_key.status_code == 422, str(no_key.status_code))
    version = first.json()["version"]["version_id"]

    status = wait_for_scan(api, app_id, version, a.scan_timeout)
    if not check("malware scan finished clean", status == "clean", status):
        return None
    extracted = api.post(f"/document-versions/{version}/extract", headers=SCRUTINY)
    if not check("text engine extracted proposed facts", extracted.status_code in (200, 201)
                 and extracted.json().get("status") == "SUCCEEDED" and extracted.json().get("fact_ids"),
                 f"{extracted.status_code} {extracted.json().get('status')}, "
                 f"{len(extracted.json().get('fact_ids') or [])} fact(s)"):
        print("      ", extracted.text[:300])
        return None
    facts = {f["field_key"]: f for f in api.get(f"/document-versions/{version}/facts", headers=SCRUTINY).json()["facts"]}
    fact = facts.get("letter_issue_date")
    if not check("issue date proposed from the letter", fact is not None, ", ".join(sorted(facts))):
        return None
    check("the suggestion is hidden before the reviewer types", fact["suggestion_visible"] is False
          and fact["candidate_text"] is None)
    inst_view = api.get(f"/document-versions/{version}/facts", headers=INST).json()
    check("institution sees no unconfirmed proposals", inst_view["facts"] == [], f"{len(inst_view['facts'])} shown")

    entry = api.post(f"/document-facts/{fact['fact_id']}/entry", headers=SCRUTINY, json={"value": "2025-03-12"})
    check("blind entry recorded, then the suggestion revealed", entry.status_code == 200
          and entry.json().get("normalized_value") == "2025-03-12", f"{entry.status_code} {entry.json()}")
    peek = api.post(f"/document-facts/{fact['fact_id']}/reveal", headers=RO_SOUTH)
    check("another officer cannot reveal someone else's entry", peek.status_code == 403, str(peek.status_code))
    reviewed = api.post(f"/document-facts/{fact['fact_id']}/review", headers={**SCRUTINY, "Idempotency-Key": key + "-r"},
                        json={"decision": "ACCEPTED"})
    check("reviewer accepts the OCR value", reviewed.status_code == 200 and reviewed.json().get("status") == "reviewed",
          f"{reviewed.status_code} {reviewed.json().get('status')}")
    own = api.post(f"/document-facts/{fact['fact_id']}/confirm", headers=SCRUTINY)
    check("four-eyes: the reviewer cannot confirm their own review", own.status_code == 409, str(own.status_code))
    confirmed = api.post(f"/document-facts/{fact['fact_id']}/confirm", headers={**RO_SOUTH, "Idempotency-Key": key + "-c"})
    check("a second officer confirms it", confirmed.status_code == 200
          and confirmed.json().get("status") == "confirmed", f"{confirmed.status_code} {confirmed.json().get('status')}")
    inst_view = api.get(f"/document-versions/{version}/facts", headers=INST).json()
    check("institution now sees the confirmed value", [f["value"] for f in inst_view["facts"]] == ["2025-03-12"],
          str([f["value"] for f in inst_view["facts"]]))
    return {"version": version, "fact": fact["fact_id"], "run": run_id}


def provide_checklist(api: httpx.Client, app_id: str, a) -> None:
    """Uploads one synthetic document per mandatory checklist item and links its clean version to the item."""
    checklist = api.get(f"/applications/{app_id}/checklist", headers=INST).json()
    items = []
    for item in checklist["items"]:
        if not item["mandatory"]:
            continue
        run_id = uuid.uuid4().hex[:8]
        doc = upload(api, app_id, item["item_key"], synthetic_pdf([f"SYNTHETIC {item['item_key']} - DEMO ONLY"]),
                     f"smoke-item-{run_id}", f"{item['item_key'].lower()}.pdf")
        if doc.status_code != 201:
            check(f"checklist document {item['item_key']} uploaded", False, f"{doc.status_code} {doc.text[:200]}")
            continue
        version = doc.json()["version"]["version_id"]
        if wait_for_scan(api, app_id, version, a.scan_timeout) == "clean":
            items.append({"item_key": item["item_key"], "state": "PROVIDED", "document_ref": version})
    linked = api.post(f"/applications/{app_id}/items", headers=INST, json={"items": items}) if items else None
    after = api.get(f"/applications/{app_id}/checklist", headers=INST).json()
    check("checklist items linked to clean document versions", linked is not None and linked.status_code == 200
          and after.get("mandatory_items_complete") is True,
          f"{len(items)} item(s){'' if linked is None else ', ' + str(linked.status_code)}")


def compliance(api: httpx.Client, app_id: str, doc: dict, a) -> None:
    letter = api.post("/compliance/letters", headers={**BUREAU, "Idempotency-Key": f"smoke-loa-{doc['run']}"}, json={
        "application_id": app_id, "institution_id": SUNRISE, "letter_type": "LOA", "academic_year": "2025-26",
        "issue_date": "2025-03-12", "issue_date_source": "CONFIRMED_FACT", "issue_date_fact_id": doc["fact"],
        "document_version_id": doc["version"], "lists_deficiencies": False})
    if not check("bureau registers the LoA from the confirmed fact", letter.status_code == 201,
                 f"{letter.status_code} {letter.text[:200] if letter.status_code != 201 else ''}"):
        return
    obligations = letter.json()["obligation_ids"]
    check("LoA created its obligations", len(obligations) == 2, f"{len(obligations)}, valid until "
          f"{letter.json().get('valid_until')}")
    refused = api.post("/compliance/letters", headers=INST, json={
        "application_id": app_id, "institution_id": SUNRISE, "letter_type": "LOA", "academic_year": "2026-27",
        "issue_date": "2025-03-12", "issue_date_source": "PORTAL_EVENT", "f_no": "F.No.DEMO",
        "lists_deficiencies": False})
    check("an institution cannot register a letter", refused.status_code == 403, str(refused.status_code))

    proof = upload(api, app_id, "SECURITY_DEPOSIT_PROOF",
                   synthetic_pdf(["SYNTHETIC DEPOSIT RECEIPT - DEMO ONLY", f"reference DEMO-{doc['run']}"]),
                   f"smoke-proof-{doc['run']}", "deposit-demo.pdf")
    if not check("evidence document uploaded", proof.status_code == 201, str(proof.status_code)):
        return
    proof_version = proof.json()["version"]["version_id"]
    if not check("evidence document scanned clean",
                 wait_for_scan(api, app_id, proof_version, a.scan_timeout) == "clean"):
        return
    ev = api.post(f"/compliance/obligations/{obligations[0]}/evidence",
                  headers={**INST, "Idempotency-Key": f"smoke-ev-{doc['run']}"},
                  json={"document_version_id": proof_version})
    if not check("institution submits evidence", ev.status_code == 201, f"{ev.status_code} {ev.text[:200]}"):
        return
    verified = api.post(f"/compliance/evidence/{ev.json()['id']}/verify",
                        headers={**RO_SOUTH, "Idempotency-Key": f"smoke-ver-{doc['run']}"}, json={"decision": "ACCEPTED"})
    check("regional officer accepts the evidence", verified.status_code == 200
          and verified.json().get("status") == "ACCEPTED", f"{verified.status_code} {verified.json().get('status')}")
    ob = api.get(f"/compliance/obligations/{obligations[0]}", headers=INST).json()
    check("obligation is met", ob.get("status") == "MET", ob.get("status", ""))


def alerts(api: httpx.Client, app_id: str) -> None:
    deadline = next((d for d in api.get(f"/deadlines?subject_id={app_id}", headers=SCRUTINY).json()
                     if d["rule_id"] == "AICTE_PROCESSING"), None)
    if not check("processing deadline open", deadline is not None):
        return
    moved = api.post("/sim/clock", headers=HEAD, json={"days": 29})
    check("time travel 29 days", moved.status_code == 200, f"offset {moved.json().get('offset_days')} day(s)")
    run = api.post("/sim/timers/run", headers=HEAD)
    check("timer run", run.status_code == 200, f"{run.json().get('processed')} deadline(s) processed")
    mine = api.get(f"/alerts?deadline_id={deadline['id']}", headers=RO_SOUTH).json()
    alert = next((x for x in mine if x["level"] == 0), None)
    if not check("regional office has the reminder", alert is not None and alert["status"] == "OPEN",
                 f"{len(mine)} alert(s)"):
        return
    wrong = api.post(f"/alerts/{alert['id']}/ack", headers=HEAD)
    check("a role the alert is not addressed to cannot acknowledge it", wrong.status_code == 403, str(wrong.status_code))
    ack = api.post(f"/alerts/{alert['id']}/ack", headers={**RO_SOUTH, "Idempotency-Key": f"smoke-ack-{alert['id'][:8]}"})
    check("regional officer acknowledges", ack.status_code == 200 and ack.json().get("status") == "ACKNOWLEDGED",
          f"{ack.status_code} {ack.json().get('status')}")
    again = api.post(f"/alerts/{alert['id']}/ack", headers=RO_SOUTH)
    check("acknowledging again changes nothing", again.status_code == 200
          and again.json().get("acknowledged_at") == ack.json().get("acknowledged_at"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--docker", action="store_true", help="deliver demo alerts via docker compose exec")
    ap.add_argument("--compose", default="", help='extra docker compose arguments, e.g. "-p demo -f a.yml -f b.yml"')
    ap.add_argument("--scan-timeout", type=float, default=180, help="seconds to wait for the malware scan")
    a = ap.parse_args()
    api = httpx.Client(base_url=f"{a.api}/api", timeout=60)

    config = api.get("/auth/config")
    if not check("demo sign-in is on", config.json()["mode"] == "demo", str(config.json()["mode"])):
        print("this script needs DEMO_AUTH=true; use scripts/smoke_security.py for real sign-in")
        return 1
    check("API responses carry the security headers", not headers_ok(config), ", ".join(headers_ok(config)))
    missing = api.get("/no-such-endpoint", headers=HEAD)
    check("error responses carry them too", missing.status_code == 404 and not headers_ok(missing),
          ", ".join(headers_ok(missing)))

    app = api.post("/applications", headers=INST, json={
        "institution_id": SUNRISE, "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()
    blocked = api.post(f"/applications/{app['id']}/submit", headers=INST, json={"dsc_present": True})
    check("submitting without the mandatory checklist items is refused", blocked.status_code == 422,
          f"{blocked.status_code} {blocked.json().get('detail')}")
    provide_checklist(api, app["id"], a)
    submitted = api.post(f"/applications/{app['id']}/submit", headers=INST, json={"dsc_present": True}).json()
    check("application submitted", submitted.get("status") == "IN_PROCESS", submitted.get("current_stage", ""))
    listed = [x["id"] for x in api.get("/applications", headers=INST).json()]
    check("visible in the institution's case list", app["id"] in listed)

    deadlines = api.get(f"/deadlines?subject_id={app['id']}", headers=SCRUTINY).json()
    if check("first deadline opened", len(deadlines) >= 1, ", ".join(d["rule_id"] for d in deadlines)):
        why = api.get(f"/deadlines/{deadlines[0]['id']}/explain", headers=INST).json()
        check("deadline explanation available", bool(why.get("explanation")), f"due {why.get('due_date')}")

    timeline = [e["event_type"] for e in api.get(f"/cases/{app['id']}/timeline", headers=INST).json()]
    check("audit timeline", "wf.application_submitted" in timeline, " -> ".join(timeline))

    doc = documents_and_review(api, app["id"], a)
    if doc:
        compliance(api, app["id"], doc, a)
    else:
        check("compliance flow (needs the confirmed fact)", False, "skipped")
    alerts(api, app["id"])

    replay = api.post("/audit/replay", headers=HEAD).json()
    check("replay ran", replay["verdict"] in ("VERIFIED_COMPLETE", "CONSISTENT_SUBSET"), replay["verdict"])
    dash = {s["key"]: s for s in api.get("/analytics/dashboard", headers=HEAD).json()["sections"]}
    check("dashboard counts applications", dash["applications"]["data"]["total"] >= 1,
          f"total {dash['applications']['data']['total']}, deadlines section {dash['deadlines']['status']}")
    card = {i["key"]: i for i in api.get("/analytics/scorecard", headers=HEAD).json()["items"]}
    for key in ("document_scanning", "four_eyes", "ocr", "alerts"):
        item = card.get(key, {})
        check(f"scorecard evaluates {key}", item.get("kind") not in (None, "NOT_EVALUATED"),
              f"{item.get('kind')} {item.get('outcome') or ''}: {item.get('finding') or item.get('note')}")
    check("scorecard: no document used before a clean scan", card.get("document_scanning", {}).get("outcome") == "PASS")
    check("scorecard: four-eyes held", card.get("four_eyes", {}).get("outcome") == "PASS")
    check("scorecard: routing honestly not evaluated without an answer key",
          card.get("routing", {}).get("kind") in ("NOT_EVALUATED", "EVALUATED_ON_ANSWER_KEY"))

    if a.docker:
        base = ["docker", "compose", *shlex.split(a.compose), "exec", "-T", "backend"]
        run = lambda *cmd: subprocess.run([*base, *cmd], capture_output=True, text=True)  # noqa: E731
        queued = run("python", "-m", "app.platform.demo_seed", "--sample-alerts")
        check("demo alerts queued (platform fixture)", queued.returncode == 0, queued.stdout.strip().splitlines()[-1:])
        delivered = run("python", "-m", "app.platform.notifier", "--once")
        check("worker ran once", delivered.returncode == 0, delivered.stderr.strip()[-200:])
        inbox = api.get("/notifications/inbox", headers=INST).json()
        check("in-app notification in the institution's inbox", len(inbox) >= 1, f"{len(inbox)} item(s)")
        delivery = {i["key"]: i for i in api.get("/analytics/scorecard", headers=HEAD).json()["items"]}
        item = delivery.get("delivery_reliability", {})
        check("scorecard measures alert delivery", item.get("kind") == "MEASURED_ON_DEMO_TRAFFIC",
              item.get("finding") or item.get("note") or "")
    else:
        print("SKIP  notification delivery (run with --docker)")

    queue = api.get("/evc/queue", headers=HEAD)
    check("EVC queue readable", queue.status_code == 200, str(queue.status_code))

    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
