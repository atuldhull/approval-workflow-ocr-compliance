"""DEMO ONLY: document validity records and a recorded undertaking on the approved demo cases.

    python -m app.workflow.demo_seed        # first: the demo cases, three of them approved with an LoA
    python -m app.compliance.demo_seed      # needs DEMO_MODE=true; safe to rerun

The approval letters and their obligations (deposit, Affidavit 3, remaining requirements) come from the workflow
seed, which issues each LoA through the case's own issue_loa action once the case has reached its decision. This
seed adds what an officer records after approval, on those same cases, through the compliance and document APIs:

- LOA-SOUTH: a land lease deed valid until 60 days from today (expiring soon), a fire safety certificate valid
  until 20 days from today with its renewal (a new version) offered and awaiting the officer's decision, and a
  structural stability certificate issued about a year ago (valid five years from issue, APH cl. 6.17(h)).
- LOA-OVERDUE: a land lease deed that expired 12 days ago; the timer run breaches it and its ladder escalates.
- LOA-NORTH: an undertaking recorded with the due date the undertaking states (21 days from today).

Dates follow the demo clock (ClockPort), never the calendar. The uploaded files are synthetic one-page PDFs this
seed builds itself; it checks them with its own scanner (recorded as "demo_seed"), which passes only those exact
bytes and leaves anything else waiting for the real scan. Every file and title is labelled DEMO.
"""
import hashlib
import io
import sys
from datetime import timedelta

from app.platform.registry import port
from contracts.ports import ClockPort

U = lambda n: f"00000000-0000-4000-9000-{n:012d}"  # noqa: E731
SUNRISE = "00000000-0000-4000-8000-000000000001"
NORTHFIELD = "00000000-0000-4000-8000-000000000002"
INST = {SUNRISE: {"X-Demo-User": U(1), "X-Demo-Role": "INSTITUTION", "X-Demo-Institution": SUNRISE},
        NORTHFIELD: {"X-Demo-User": U(4), "X-Demo-Role": "INSTITUTION", "X-Demo-Institution": NORTHFIELD}}
RO = {SUNRISE: {"X-Demo-User": U(5), "X-Demo-Role": "RO_OFFICER", "X-Demo-Region": "Southern"},
      NORTHFIELD: {"X-Demo-User": U(8), "X-Demo-Role": "RO_OFFICER", "X-Demo-Region": "Northern"}}
BUREAU = {"X-Demo-User": U(6), "X-Demo-Role": "BUREAU_OFFICER"}
BUREAU_HEAD = {"X-Demo-User": U(7), "X-Demo-Role": "BUREAU_HEAD"}
F_NO_PREFIX = "F.No. DEMO-SEED/"
UNDERTAKING_TITLE = "Undertaking: complete the additional laboratory before the next academic session (DEMO)"

# (case key, doc_type, how the date is recorded, days from today, renewal offered)
VALIDITY = (
    ("LOA-SOUTH", "LEASE_DEED", "valid_until", 60, False),
    ("LOA-SOUTH", "FIRE_NOC", "valid_until", 20, True),
    ("LOA-SOUTH", "STRUCTURAL_STABILITY", "issue_date", -400, False),
    ("LOA-OVERDUE", "LEASE_DEED", "valid_until", -12, False),
)


class SeedScanner:
    """Passes only the synthetic files this seed built; anything else stays scan_pending for the real scanner."""
    scanner_key = "demo_seed"

    def __init__(self):
        self.allowed: set[str] = set()

    def scan(self, source):
        from app.documents.scanning import ScannerUnavailable, ScanResult, ScanVerdict

        if hashlib.sha256(source.read()).hexdigest() not in self.allowed:
            raise ScannerUnavailable("not a file built by the demo seed")
        return ScanResult(ScanVerdict.CLEAN)


def synthetic_pdf(marker: str) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_metadata({"/Title": f"SYNTHETIC DEMO DOCUMENT - NOT A REAL CERTIFICATE - {marker}"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def ok(response):
    if response.status_code not in (200, 201):
        raise RuntimeError(f"{response.request.method} {response.request.url.path}: "
                           f"{response.status_code} {response.text[:300]}")
    return response.json()


def demo_cases(client) -> dict[str, dict]:
    """The approved demo cases, by key, read from the LoAs the workflow seed issued."""
    cases = {}
    for letter in ok(client.get("/api/compliance/letters", headers=BUREAU)):
        f_no = letter.get("f_no") or ""
        if letter["letter_type"] == "LOA" and f_no.startswith(F_NO_PREFIX):
            cases[f_no[len(F_NO_PREFIX):].split("/")[0]] = letter
    return cases


def upload(client, scanner: SeedScanner, letter: dict, doc_type: str, marker: str) -> str:
    content = synthetic_pdf(marker)
    scanner.allowed.add(hashlib.sha256(content).hexdigest())
    headers = {**INST[str(letter["institution_id"])], "Idempotency-Key": f"demo-seed-{marker}"}
    body = ok(client.post(f"/api/applications/{letter['application_id']}/documents", headers=headers,
                          data={"doc_type": doc_type},
                          files={"file": (f"{marker.lower()}.pdf", content, "application/pdf")}))
    version = body["version"]["version_id"]
    if body["version"].get("scan_status") == "scan_pending":
        client.post(f"/api/document-versions/{version}/scan", headers=headers)
    return version


def seed(client) -> dict[str, int]:
    """Adds the records that do not exist yet. Returns how many of each were added."""
    from app.compliance.service import IST
    from app.documents import service as documents

    today = port(ClockPort).now().astimezone(IST).date()
    cases = demo_cases(client)
    missing = sorted(({key for key, *_ in VALIDITY} | {"LOA-NORTH"}) - set(cases))
    if missing:
        raise RuntimeError(f"approved demo cases not found ({', '.join(missing)}): run app.workflow.demo_seed first")
    added = {"validity": 0, "renewal": 0, "undertaking": 0}
    scanner = SeedScanner()
    documents.configure(scanner=scanner)
    try:
        for key, doc_type, field, days, renewal in VALIDITY:
            letter = cases[key]
            institution = str(letter["institution_id"])
            records = [o for o in ok(client.get("/api/compliance/obligations", headers=BUREAU, params={
                "application_id": letter["application_id"], "kind": "DOCUMENT_VALIDITY"})) if o["doc_type"] == doc_type]
            if not records:
                version = upload(client, scanner, letter, doc_type, f"{key}-{doc_type}-V1")
                body = {"document_version_id": version, field: (today + timedelta(days=days)).isoformat()}
                if doc_type == "LEASE_DEED":
                    body["max_course_duration_years"] = 4
                records = [ok(client.post("/api/compliance/validity", headers={
                    **RO[institution], "Idempotency-Key": f"demo-seed-validity-{key}-{doc_type}"}, json=body))]
                added["validity"] += 1
            record = records[0]
            if renewal and not record["evidence"]:
                version = upload(client, scanner, letter, doc_type, f"{key}-{doc_type}-V2")
                ok(client.post(f"/api/compliance/obligations/{record['id']}/evidence", headers={
                    **INST[institution], "Idempotency-Key": f"demo-seed-renewal-{key}-{doc_type}"},
                    json={"document_version_id": version}))
                added["renewal"] += 1
    finally:
        documents.configure(scanner=None)

    letter = cases["LOA-NORTH"]
    recorded = ok(client.get("/api/compliance/obligations", headers=BUREAU, params={
        "application_id": letter["application_id"], "kind": "UNDERTAKING"}))
    if not any(o["title"] == UNDERTAKING_TITLE for o in recorded):
        ok(client.post("/api/compliance/obligations", headers={**BUREAU, "Idempotency-Key": "demo-seed-undertaking"},
                       json={"application_id": letter["application_id"], "kind": "UNDERTAKING",
                             "title": UNDERTAKING_TITLE, "source_clause": "Undertaking (DEMO)",
                             "evidence_required": "Completion certificate for the additional laboratory (DEMO)",
                             "due_date": (today + timedelta(days=21)).isoformat()}))
        added["undertaking"] += 1
    # breach the expired record now rather than at the timer worker's next poll
    ok(client.post("/api/sim/timers/run", headers=BUREAU_HEAD, json={}))
    return added


def main() -> int:
    from app.platform.demo_seed import demo_client
    from app.platform.settings import settings

    if not settings.demo_mode:
        print("refusing: DEMO_MODE is not enabled")
        return 1
    with demo_client() as client:
        added = seed(client)
    print(f"added DEMO compliance records: {added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
