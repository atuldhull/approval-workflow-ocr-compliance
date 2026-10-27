"""Document endpoints end to end: upload, scan, extraction, visibility, review and four-eyes confirmation.

Uses the shared disposable-database `client` fixture. Storage is a private temp
directory; the scanner and text engine are fakes (the real clamd adapter has its
own test that runs only when clamd is reachable).
"""
import io
import json
import socket
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from pypdf import PdfWriter
from sqlalchemy import func, select

from app.documents import service
from app.documents.config import DocumentLimits
from app.documents.extraction import PageText, TextEngineError
from app.documents.models import Document, DocumentVersion, Fact, OcrRun
from app.documents.ocr import OcrToken, Script
from app.documents.scanning import ClamdScanner, ScannerUnavailable, ScanResult, ScanVerdict
from app.documents.states import OcrErrorCode
from app.documents.storage import LocalQuarantineStorage
from app.platform.db import new_session
from app.platform.models import DomainEvent
from conftest import NORTHFIELD, SUNRISE, headers
from contracts.errors import Conflict

INST = headers("INSTITUTION", SUNRISE, user="00000000-0000-4000-9000-000000000101")
NORTH_INST = headers("INSTITUTION", NORTHFIELD, user="00000000-0000-4000-9000-000000000102")
COMMITTEE = headers("SCRUTINY_COMMITTEE", user="00000000-0000-4000-9000-000000000103")
COMMITTEE_2 = headers("SCRUTINY_COMMITTEE", user="00000000-0000-4000-9000-000000000104")
RO_SOUTH = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000105"), "X-Demo-Region": "Southern"}
RO_NORTH = {**headers("RO_OFFICER", user="00000000-0000-4000-9000-000000000106"), "X-Demo-Region": "Northern"}
BUREAU = headers("BUREAU_OFFICER", user="00000000-0000-4000-9000-000000000107")
AUDITOR = headers("AUDITOR", user="00000000-0000-4000-9000-000000000108")

PAGE = "letter_issue_date: 2025-03-12\nletter_file_number: F.No.42/2025"


class FakeScanner:
    scanner_key = "clamav"

    def __init__(self):
        self.down = False
        self.calls = 0
        self.infected: set[bytes] = set()  # synthetic files this fake reports as malware

    def scan(self, source):
        self.calls += 1
        if self.down:
            raise ScannerUnavailable("scanner offline")
        if source.read() in self.infected:
            return ScanResult(ScanVerdict.INFECTED, "Synthetic.Test-Signature")
        return ScanResult(ScanVerdict.CLEAN)


class FakeEngine:
    adapter_key = "test.fake"
    model_version = "fixture-1"

    def __init__(self, text=PAGE):
        self.text = text
        self.fail: OcrErrorCode | None = None

    def read(self, content, *, media_type):
        if self.fail:
            raise TextEngineError(self.fail)
        tokens, offset = [], 0
        for word in self.text.replace("\n", " ").split(" "):
            start = self.text.index(word, offset)
            tokens.append(OcrToken(word, 1, start, start + len(word), Decimal("0.9"), Script.LATIN))
            offset = start + len(word)
        return [PageText(1, self.text, tuple(tokens))]


@pytest.fixture
def docs(client, tmp_path):
    store = tmp_path / "store"
    scanner, engine = FakeScanner(), FakeEngine()
    service.configure(storage=LocalQuarantineStorage(store, limits=DocumentLimits(10 * 1024 * 1024, 20, 4_000_000)),
                      scanner=scanner, engine=engine)
    yield type("Docs", (), {"client": client, "store": store, "scanner": scanner, "engine": engine})
    service.configure(storage=None, scanner=None, engine=None)


def pdf(marker: str = "a") -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": marker})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def new_application(client, h=INST, institution=SUNRISE) -> str:
    r = client.post("/api/applications", headers=h, json={
        "institution_id": str(institution), "category": "NEW_PROGRAMME", "academic_year": "2027-28"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(client, app_id, content, key="upload-key-0001", h=INST, doc_type="LAND_DEED", name="deed.pdf"):
    extra = {"Idempotency-Key": key} if key else {}
    return client.post(f"/api/applications/{app_id}/documents", headers={**h, **extra},
                       data={"doc_type": doc_type}, files={"file": (name, content, "application/pdf")})


def events(prefix="doc."):
    with new_session() as s:
        return [(e.event_type, e.payload) for e in
                s.scalars(select(DomainEvent).where(DomainEvent.event_type.like(f"{prefix}%"))
                          .order_by(DomainEvent.seq)).all()]


def count(model, *where):
    with new_session() as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


def stored_objects(store: Path) -> int:
    root = store / "quarantine"
    return sum(1 for p in root.rglob("*") if p.is_file()) if root.exists() else 0


def clean_version(docs, app_id=None, marker="clean-1"):
    app_id = app_id or new_application(docs.client)
    r = upload(docs.client, app_id, pdf(marker), key=f"clean-key-{marker}")
    assert r.status_code == 201, r.text
    return app_id, r.json()["version"]["version_id"]


def extracted(docs):
    app_id, version_id = clean_version(docs)
    r = docs.client.post(f"/api/document-versions/{version_id}/extract", headers=COMMITTEE)
    assert r.status_code == 201, r.text
    return app_id, version_id, r.json()["fact_ids"]


def fact_id_for(docs, version_id, field):
    facts = docs.client.get(f"/api/document-versions/{version_id}/facts", headers=BUREAU).json()["facts"]
    return next(f["fact_id"] for f in facts if f["field_key"] == field)


# ---- upload, versions, duplicates, idempotency ----

def test_upload_is_quarantined_then_scanned_clean_with_both_events(docs):
    app_id = new_application(docs.client)
    r = upload(docs.client, app_id, pdf())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] is True and body["version"]["version_no"] == 1
    assert body["version"]["scan_status"] == "scan_pending"   # committed state; the scan runs after the response

    listed = docs.client.get(f"/api/applications/{app_id}/documents", headers=INST).json()
    assert listed[0]["doc_type"] == "LAND_DEED"
    assert listed[0]["versions"][0]["scan_status"] == "clean"
    assert listed[0]["current_version_id"] == body["version"]["version_id"]

    emitted = events()
    assert [t for t, _ in emitted] == ["doc.document_uploaded", "doc.document_scanned"]
    uploaded, scanned = emitted[0][1], emitted[1][1]
    assert set(uploaded) == {"document_id", "version_id", "version_no", "application_id", "institution_id",
                             "doc_type", "sha256", "size_bytes", "media_type"}
    assert uploaded["sha256"] == sha256(pdf()).hexdigest()
    assert scanned["verdict"] == "CLEAN" and "signature" not in scanned
    assert "deed.pdf" not in json.dumps(emitted)                # no file names in events


def test_upload_requires_an_idempotency_key(docs):
    app_id = new_application(docs.client)
    r = upload(docs.client, app_id, pdf(), key=None)
    assert r.status_code == 422 and "Idempotency-Key" in r.text
    assert count(DocumentVersion) == 0 and stored_objects(docs.store) == 0


def test_retry_with_the_same_key_replays_and_a_reused_key_for_other_bytes_is_refused(docs):
    app_id = new_application(docs.client)
    first = upload(docs.client, app_id, pdf(), key="retry-key-01")
    again = upload(docs.client, app_id, pdf(), key="retry-key-01")
    assert again.status_code == first.status_code == 201
    assert again.json() == first.json() and again.headers["Idempotent-Replayed"] == "true"
    other = upload(docs.client, app_id, pdf("changed"), key="retry-key-01")
    assert other.status_code == 422 and "different request" in other.text
    assert count(DocumentVersion) == 1
    assert [t for t, _ in events()].count("doc.document_uploaded") == 1
    assert stored_objects(docs.store) == 1                     # retries' copies were removed


def test_same_bytes_return_the_existing_version_but_are_separate_for_another_application(docs):
    app_a, app_b = new_application(docs.client), new_application(docs.client)
    north = new_application(docs.client, NORTH_INST, NORTHFIELD)
    first = upload(docs.client, app_a, pdf(), key="dup-key-0001")
    dup = upload(docs.client, app_a, pdf(), key="dup-key-0002")
    assert dup.status_code == 200 and dup.json()["created"] is False
    assert dup.json()["version"]["version_id"] == first.json()["version"]["version_id"]

    assert upload(docs.client, app_b, pdf(), key="dup-key-0003").status_code == 201
    assert upload(docs.client, north, pdf(), key="dup-key-0004", h=NORTH_INST).status_code == 201
    other_item = upload(docs.client, app_a, pdf(), key="dup-key-0005", doc_type="FIRE_NOC")
    assert other_item.status_code == 409

    assert count(DocumentVersion) == 3 and count(Document, Document.doc_type.is_not(None)) == 3
    assert [t for t, _ in events()].count("doc.document_uploaded") == 3
    assert stored_objects(docs.store) == 3


def test_new_bytes_add_a_version_and_the_current_version_is_the_newest_clean_one(docs):
    app_id, v1 = clean_version(docs, marker="v1")
    docs.scanner.down = True
    r = upload(docs.client, app_id, pdf("v2"), key="key-v2-0001")
    assert r.status_code == 201 and r.json()["version"]["version_no"] == 2
    doc = docs.client.get(f"/api/applications/{app_id}/documents", headers=INST).json()[0]
    assert [v["version_no"] for v in doc["versions"]] == [2, 1]
    assert doc["current_version_id"] == v1                       # v2 is still scan_pending
    docs.scanner.down = False
    v2 = r.json()["version"]["version_id"]
    assert docs.client.post(f"/api/document-versions/{v2}/scan", headers=INST).json()["scan_status"] == "clean"
    doc = docs.client.get(f"/api/applications/{app_id}/documents", headers=INST).json()[0]
    assert doc["current_version_id"] == v2


@pytest.mark.parametrize("h", [NORTH_INST, COMMITTEE, RO_SOUTH, BUREAU, AUDITOR])
def test_only_the_owning_institution_may_upload(docs, h):
    app_id = new_application(docs.client)
    r = upload(docs.client, app_id, pdf(), h=h)
    assert r.status_code == 403
    assert count(DocumentVersion) == 0 and stored_objects(docs.store) == 0


def test_bad_doc_type_and_bad_files_are_rejected(docs):
    app_id = new_application(docs.client)
    assert upload(docs.client, app_id, pdf(), doc_type="land deed").status_code == 422
    assert upload(docs.client, app_id, b"MZ not a document").status_code == 422
    assert count(DocumentVersion) == 0 and stored_objects(docs.store) == 0


def test_a_failed_upload_rolls_back_leaving_no_row_no_event_and_no_file(docs, monkeypatch):
    app_id = new_application(docs.client)
    real = service._event

    def fail_after_event(*args, **kwargs):
        real(*args, **kwargs)
        raise Conflict("simulated failure after the event was written")

    monkeypatch.setattr(service, "_event", fail_after_event)
    assert upload(docs.client, app_id, pdf()).status_code == 409
    assert count(Document) == 0 and count(DocumentVersion) == 0
    assert events() == [] and stored_objects(docs.store) == 0
    monkeypatch.setattr(service, "_event", real)
    assert upload(docs.client, app_id, pdf()).status_code == 201   # the same key works after a rollback


# ---- malware scan ----

def test_scanner_down_keeps_the_version_pending_unserved_and_rescannable(docs):
    docs.scanner.down = True
    app_id = new_application(docs.client)
    version_id = upload(docs.client, app_id, pdf()).json()["version"]["version_id"]
    doc = docs.client.get(f"/api/applications/{app_id}/documents", headers=INST).json()[0]
    assert doc["versions"][0]["scan_status"] == "scan_pending" and doc["current_version_id"] is None
    assert docs.client.post(f"/api/document-versions/{version_id}/extract", headers=COMMITTEE).status_code == 409
    assert docs.client.post(f"/api/document-versions/{version_id}/scan", headers=INST).status_code == 503
    assert [t for t, _ in events()] == ["doc.document_uploaded"]

    assert docs.client.post(f"/api/document-versions/{version_id}/scan", headers=RO_SOUTH).status_code == 403
    docs.scanner.down = False
    assert docs.client.post(f"/api/document-versions/{version_id}/scan", headers=INST).json()["scan_status"] == "clean"
    assert docs.client.post(f"/api/document-versions/{version_id}/scan", headers=INST).json()["scan_status"] == "clean"
    assert [t for t, _ in events()] == ["doc.document_uploaded", "doc.document_scanned"]


def test_an_infected_version_stays_in_quarantine_and_never_gets_facts(docs):
    app_id = new_application(docs.client)
    docs.scanner.infected.add(pdf("infected"))
    version_id = upload(docs.client, app_id, pdf("infected")).json()["version"]["version_id"]
    doc = docs.client.get(f"/api/applications/{app_id}/documents", headers=INST).json()[0]
    assert doc["versions"][0]["scan_status"] == "infected" and doc["current_version_id"] is None
    with new_session() as s:
        assert s.get(DocumentVersion, UUID(version_id)).status == "REJECTED"
    assert docs.client.post(f"/api/document-versions/{version_id}/extract", headers=COMMITTEE).status_code == 409
    scanned = events()[-1]
    assert scanned[0] == "doc.document_scanned"
    assert scanned[1]["verdict"] == "INFECTED" and scanned[1]["signature"] == "Synthetic.Test-Signature"


# ---- extraction and visibility ----

def test_extraction_returns_ids_only_and_is_not_repeated(docs):
    _, version_id = clean_version(docs)
    r = docs.client.post(f"/api/document-versions/{version_id}/extract", headers=COMMITTEE)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "SUCCEEDED" and len(body["fact_ids"]) == 2
    assert "2025-03-12" not in r.text and "F.No" not in r.text   # no extracted values in the response
    again = docs.client.post(f"/api/document-versions/{version_id}/extract", headers=COMMITTEE)
    assert again.status_code == 200 and again.json()["ocr_run_id"] == body["ocr_run_id"]
    assert count(OcrRun) == 1 and count(Fact) == 2


def test_a_failed_extraction_is_recorded_and_retried_as_a_new_attempt(docs):
    _, version_id = clean_version(docs)
    docs.engine.fail = OcrErrorCode.TIMEOUT
    r = docs.client.post(f"/api/document-versions/{version_id}/extract", headers=RO_SOUTH)
    assert r.json()["status"] == "FAILED" and r.json()["error_code"] == "TIMEOUT"
    docs.engine.fail = None
    r = docs.client.post(f"/api/document-versions/{version_id}/extract", headers=RO_SOUTH)
    assert r.json()["status"] == "SUCCEEDED" and r.json()["attempt_number"] == 2


def test_extraction_rolls_back_if_its_commit_fails(docs, monkeypatch):
    """Commit before reveal: if the transaction does not commit, the caller gets no ids and nothing is stored."""
    _, version_id = clean_version(docs)
    real = service.unit_of_work

    from contextlib import contextmanager

    @contextmanager
    def commit_fails(principal):
        with real(principal) as uow:
            yield uow
            raise Conflict("simulated commit failure")

    monkeypatch.setattr(service, "unit_of_work", commit_fails)
    r = docs.client.post(f"/api/document-versions/{version_id}/extract", headers=COMMITTEE)
    assert r.status_code == 409 and "fact_ids" not in r.text
    assert count(OcrRun) == 0 and count(Fact) == 0


@pytest.mark.parametrize("h, code", [(INST, 403), (NORTH_INST, 403), (BUREAU, 403), (AUDITOR, 403),
                                     (RO_NORTH, 403), (RO_SOUTH, 201), (COMMITTEE, 201)])
def test_who_may_extract(docs, h, code):
    _, version_id = clean_version(docs)
    assert docs.client.post(f"/api/document-versions/{version_id}/extract", headers=h).status_code == code


def test_institutions_never_see_proposals_and_reviewers_see_values_only_after_entry(docs):
    _, version_id, _ = extracted(docs)
    inst = docs.client.get(f"/api/document-versions/{version_id}/facts", headers=INST).json()
    assert inst["facts"] == [] and inst["review_status"]["proposed"] == 2
    assert docs.client.get(f"/api/document-versions/{version_id}/facts", headers=NORTH_INST).status_code == 403
    assert docs.client.get(f"/api/document-versions/{version_id}/facts", headers=RO_NORTH).status_code == 403

    for h in (COMMITTEE, RO_SOUTH):
        facts = docs.client.get(f"/api/document-versions/{version_id}/facts", headers=h).json()["facts"]
        assert len(facts) == 2 and all(f["candidate_text"] is None and not f["suggestion_visible"] for f in facts)
    for h in (BUREAU, AUDITOR):
        facts = docs.client.get(f"/api/document-versions/{version_id}/facts", headers=h).json()["facts"]
        assert {f["normalized_value"] for f in facts} == {"2025-03-12", "F.No.42/2025"}


# ---- review and confirmation ----

def test_entry_commits_before_the_suggestion_is_revealed(docs, monkeypatch):
    _, version_id, _ = extracted(docs)
    fact_id = fact_id_for(docs, version_id, "letter_issue_date")

    def reveal_fails(uow, fact_id):
        raise Conflict("simulated failure while revealing")

    real = service.reveal_for_reviewer
    monkeypatch.setattr(service, "reveal_for_reviewer", reveal_fails)
    r = docs.client.post(f"/api/document-facts/{fact_id}/entry", headers=COMMITTEE, json={"value": "2025-03-12"})
    assert r.status_code == 409 and "2025-03-12" not in r.text
    with new_session() as s:
        fact = s.get(Fact, UUID(fact_id))
        assert fact.review_typed_value == "2025-03-12" and fact.suggestion_revealed_at is None
    monkeypatch.setattr(service, "reveal_for_reviewer", real)
    assert docs.client.post(f"/api/document-facts/{fact_id}/reveal", headers=COMMITTEE_2).status_code == 403
    shown = docs.client.post(f"/api/document-facts/{fact_id}/reveal", headers=COMMITTEE)
    assert shown.status_code == 200 and shown.json()["normalized_value"] == "2025-03-12"


def test_review_then_confirm_by_another_officer_with_events(docs):
    app_id, version_id, _ = extracted(docs)
    fact_id = fact_id_for(docs, version_id, "letter_issue_date")
    assert docs.client.post(f"/api/document-facts/{fact_id}/confirm", headers=BUREAU).status_code == 409

    entry = docs.client.post(f"/api/document-facts/{fact_id}/entry", headers=COMMITTEE, json={"value": "2025-03-12"})
    assert entry.status_code == 200 and entry.json()["normalized_value"] == "2025-03-12"
    for h in (INST, BUREAU, AUDITOR, RO_NORTH):
        assert docs.client.post(f"/api/document-facts/{fact_id}/review", headers=h,
                                json={"decision": "ACCEPTED"}).status_code == 403
    assert docs.client.post(f"/api/document-facts/{fact_id}/review", headers=COMMITTEE_2,
                            json={"decision": "ACCEPTED"}).status_code == 409   # only the officer who entered
    reviewed = docs.client.post(f"/api/document-facts/{fact_id}/review", headers=COMMITTEE,
                                json={"decision": "ACCEPTED", "note": "matches the synthetic letter"})
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "reviewed"
    assert reviewed.json()["review_decision"] == "ACCEPTED"

    # four-eyes: the reviewer may not confirm; an institution never confirms
    refused = docs.client.post(f"/api/document-facts/{fact_id}/confirm", headers=COMMITTEE)
    assert refused.status_code == 409 and refused.json()["error"] == "FourEyesViolation"
    assert docs.client.post(f"/api/document-facts/{fact_id}/confirm", headers=INST).status_code == 403
    assert docs.client.post(f"/api/document-facts/{fact_id}/confirm", headers=AUDITOR).status_code == 403
    confirmed = docs.client.post(f"/api/document-facts/{fact_id}/confirm", headers=COMMITTEE_2)
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    assert docs.client.post(f"/api/document-facts/{fact_id}/confirm", headers=BUREAU).status_code == 409

    inst = docs.client.get(f"/api/document-versions/{version_id}/facts", headers=INST).json()
    assert inst["facts"] == [{"fact_id": fact_id, "field_key": "letter_issue_date", "status": "confirmed",
                              "value": "2025-03-12", "page_number": 1,
                              "confirmed_at": inst["facts"][0]["confirmed_at"]}]
    assert inst["review_status"]["confirmed"] == 1 and inst["review_status"]["proposed"] == 1

    emitted = dict(events())
    review_payload, confirm_payload = emitted["doc.fact_reviewed"], emitted["doc.fact_confirmed"]
    digest = sha256(b"2025-03-12").hexdigest()
    assert review_payload["value_hash"] == digest and review_payload["decision"] == "ACCEPTED"
    assert len(review_payload["note_hash"]) == 64
    assert confirm_payload["value_hash"] == digest and confirm_payload["field"] == "letter_issue_date"
    raw = json.dumps([p for _, p in events()])
    assert "2025-03-12" not in raw and "synthetic letter" not in raw and "F.No" not in raw

    with new_session() as s:
        assert [f.fact_id for f in service.confirmed_facts(s, UUID(app_id))] == [UUID(fact_id)]


def test_corrected_and_rejected_reviews(docs):
    _, version_id, _ = extracted(docs)
    date_fact = fact_id_for(docs, version_id, "letter_issue_date")
    ref_fact = fact_id_for(docs, version_id, "letter_file_number")
    docs.client.post(f"/api/document-facts/{date_fact}/entry", headers=RO_SOUTH, json={"value": "2025-03-13"})
    r = docs.client.post(f"/api/document-facts/{date_fact}/review", headers=RO_SOUTH,
                         json={"decision": "CORRECTED", "value": "2025-03-13"})
    assert r.status_code == 200 and r.json()["reviewed_value"] == "2025-03-13"
    assert docs.client.post(f"/api/document-facts/{date_fact}/confirm", headers=BUREAU).status_code == 200

    docs.client.post(f"/api/document-facts/{ref_fact}/entry", headers=RO_SOUTH, json={"value": "unreadable"})
    r = docs.client.post(f"/api/document-facts/{ref_fact}/review", headers=RO_SOUTH, json={"decision": "REJECTED"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert docs.client.post(f"/api/document-facts/{ref_fact}/confirm", headers=BUREAU).status_code == 409


def test_review_and_confirm_honour_an_idempotency_key(docs):
    _, version_id, _ = extracted(docs)
    fact_id = fact_id_for(docs, version_id, "letter_issue_date")
    docs.client.post(f"/api/document-facts/{fact_id}/entry", headers=COMMITTEE, json={"value": "2025-03-12"})
    h = {**COMMITTEE, "Idempotency-Key": "review-key-01"}
    first = docs.client.post(f"/api/document-facts/{fact_id}/review", headers=h, json={"decision": "ACCEPTED"})
    again = docs.client.post(f"/api/document-facts/{fact_id}/review", headers=h, json={"decision": "ACCEPTED"})
    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    assert again.headers["Idempotent-Replayed"] == "true"
    c = {**BUREAU, "Idempotency-Key": "confirm-key-01"}
    assert docs.client.post(f"/api/document-facts/{fact_id}/confirm", headers=c).status_code == 200
    assert docs.client.post(f"/api/document-facts/{fact_id}/confirm", headers=c).headers["Idempotent-Replayed"] == "true"
    types = [t for t, _ in events()]
    assert types.count("doc.fact_reviewed") == 1 and types.count("doc.fact_confirmed") == 1


def test_the_database_also_refuses_a_self_confirmation(docs):
    _, version_id, _ = extracted(docs)
    fact_id = fact_id_for(docs, version_id, "letter_issue_date")
    docs.client.post(f"/api/document-facts/{fact_id}/entry", headers=COMMITTEE, json={"value": "2025-03-12"})
    docs.client.post(f"/api/document-facts/{fact_id}/review", headers=COMMITTEE, json={"decision": "ACCEPTED"})
    from sqlalchemy.exc import IntegrityError
    with new_session() as s:
        fact = s.get(Fact, UUID(fact_id))
        fact.confirmed_by, fact.confirmed_at = fact.review_typed_by, fact.reviewed_at
        with pytest.raises(IntegrityError):
            s.commit()


# ---- listing across applications ----

def test_document_lists_are_scoped_by_region_and_institution(docs):
    south_app = new_application(docs.client)
    north_app = new_application(docs.client, NORTH_INST, NORTHFIELD)
    upload(docs.client, south_app, pdf("south"), key="list-key-01")
    upload(docs.client, north_app, pdf("north"), key="list-key-02", h=NORTH_INST)

    def apps(h, query=""):
        r = docs.client.get(f"/api/documents{query}", headers=h)
        return r.status_code, sorted(d["application_id"] for d in r.json()) if r.status_code == 200 else None

    assert apps(RO_SOUTH) == (200, [south_app])
    assert apps(RO_SOUTH, "?region=Northern")[0] == 403
    assert apps(BUREAU) == (200, sorted([south_app, north_app]))
    assert apps(BUREAU, "?region=Northern") == (200, [north_app])
    assert apps(NORTH_INST) == (200, [north_app])
    assert docs.client.get(f"/api/applications/{south_app}/documents", headers=NORTH_INST).status_code == 403
    assert docs.client.get(f"/api/applications/{south_app}/documents", headers=RO_NORTH).status_code == 403


# ---- the clamd adapter ----

def test_clamd_replies_are_parsed_strictly():
    assert ClamdScanner.parse_reply(b"stream: OK\0").verdict is ScanVerdict.CLEAN
    infected = ClamdScanner.parse_reply(b"stream: Eicar-Test-Signature FOUND\0")
    assert infected.verdict is ScanVerdict.INFECTED and infected.signature == "Eicar-Test-Signature"
    for reply in (b"INSTREAM size limit exceeded. ERROR\0", b"", b"stream: something odd\0"):
        with pytest.raises(ScannerUnavailable):
            ClamdScanner.parse_reply(reply)


def test_an_unreachable_clamd_is_unavailable_not_clean():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]               # nothing listens here once the socket closes
    with pytest.raises(ScannerUnavailable):
        ClamdScanner("127.0.0.1", port, timeout=2).scan(io.BytesIO(b"%PDF-"))


def _clamd_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 3310), timeout=1) as conn:
            conn.sendall(b"zPING\0")
            return conn.recv(16).startswith(b"PONG")
    except OSError:
        return False


@pytest.mark.skipif(not _clamd_up(), reason="clamd is not running (docker compose --profile scanning up -d clamav)")
def test_real_clamd_detects_the_standard_test_file():
    # EICAR is the industry-standard harmless antivirus test string, assembled here so this file is not flagged.
    eicar = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*").encode()
    scanner = ClamdScanner()
    assert scanner.scan(io.BytesIO(pdf())).verdict is ScanVerdict.CLEAN
    result = scanner.scan(io.BytesIO(eicar))
    assert result.verdict is ScanVerdict.INFECTED and "Eicar" in result.signature


# ---- viewing the stored file ----

CONTENT = "/api/document-versions/{}/content"


def test_a_clean_version_is_served_inline_with_locked_down_headers(docs):
    app_id = new_application(docs.client)
    body = pdf("viewable")
    r = upload(docs.client, app_id, body, key="view-key-1", name="lease deedé;x.pdf")
    version_id = r.json()["version"]["version_id"]
    assert r.json()["version"]["status"] == "QUARANTINED"  # until the scan that runs after the upload commits

    got = docs.client.get(CONTENT.format(version_id), headers=COMMITTEE)
    assert got.status_code == 200 and got.content == body
    assert got.headers["content-type"] == "application/pdf"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["cache-control"] == "private, no-store"
    assert got.headers["content-security-policy"] == "default-src 'none'; sandbox"
    disposition = got.headers["content-disposition"]
    assert disposition == "inline; filename=\"lease deed__x.pdf\"; filename*=UTF-8''lease%20deed%C3%A9%3Bx.pdf"


def test_content_disposition_never_lets_a_filename_break_out():
    from app.documents.api import content_disposition

    value = content_disposition('x"y\r\nSet-Cookie: z.pdf')
    assert value == "inline; filename=\"x_ySet-Cookie_ z.pdf\"; filename*=UTF-8''x%22ySet-Cookie%3A%20z.pdf"
    assert content_disposition("..\\..\\secret/c.pdf").startswith('inline; filename="c.pdf"')
    assert content_disposition("").startswith('inline; filename="upload"')


@pytest.mark.parametrize("h,code", [(INST, 200), (NORTH_INST, 403), (COMMITTEE, 200), (RO_SOUTH, 200),
                                    (RO_NORTH, 403), (BUREAU, 200), (AUDITOR, 200)])
def test_who_may_view_a_version(docs, h, code):
    _, version_id = clean_version(docs, marker="who-views")
    assert docs.client.get(CONTENT.format(version_id), headers=h).status_code == code


def test_committee_viewing_follows_the_assignment_rule(docs, monkeypatch):
    from dataclasses import replace

    from app.platform import auth

    _, version_id = clean_version(docs, marker="assigned")
    monkeypatch.setattr(auth, "settings", replace(auth.settings, authz_require_assignment=True))
    assert docs.client.get(CONTENT.format(version_id), headers=COMMITTEE).status_code == 403
    assert docs.client.get(CONTENT.format(version_id), headers=RO_SOUTH).status_code == 200


def test_quarantined_and_rejected_versions_are_never_served(docs):
    app_id = new_application(docs.client)
    docs.scanner.down = True
    pending = upload(docs.client, app_id, pdf("pending"), key="view-key-p").json()["version"]
    assert pending["status"] == "QUARANTINED" and pending["scan_status"] == "scan_pending"
    docs.scanner.down = False
    docs.scanner.infected.add(pdf("bad"))
    infected = upload(docs.client, app_id, pdf("bad"), key="view-key-i", doc_type="FIRE_NOC").json()["version"]
    listed = docs.client.get(f"/api/applications/{app_id}/documents", headers=INST).json()
    assert {v["status"] for d in listed for v in d["versions"]} == {"QUARANTINED", "REJECTED"}
    for version, word in ((pending, "malware scan"), (infected, "rejected")):
        for h in (INST, BUREAU):
            r = docs.client.get(CONTENT.format(version["version_id"]), headers=h)
            assert r.status_code == 409 and r.json()["error"] == "DocumentNotViewable"
            assert word in r.json()["detail"] and "%PDF" not in r.text
    # authorization still comes first: another institution learns nothing about the version
    assert docs.client.get(CONTENT.format(pending["version_id"]), headers=NORTH_INST).status_code == 403
    assert docs.client.get(CONTENT.format("00000000-0000-4000-8000-00000000dead"), headers=BUREAU).status_code == 404


def test_stored_bytes_that_no_longer_match_the_upload_are_not_served(docs):
    _, version_id = clean_version(docs, marker="tampered")
    with new_session() as s:
        ref = s.get(DocumentVersion, UUID(version_id)).storage_ref
    path = docs.store.joinpath(*ref.split("/"))
    path.write_bytes(path.read_bytes() + b"appended")
    r = docs.client.get(CONTENT.format(version_id), headers=BUREAU)
    assert r.status_code == 409 and r.json()["error"] == "StoredContentMismatch"


def test_document_listings_show_the_version_lifecycle_status(docs):
    app_id, version_id = clean_version(docs, marker="status")
    doc = docs.client.get(f"/api/applications/{app_id}/documents", headers=INST).json()[0]
    assert doc["versions"][0]["status"] == "AVAILABLE" and doc["versions"][0]["scan_status"] == "clean"
    listed = docs.client.get("/api/documents", headers=BUREAU).json()
    assert {v["status"] for d in listed for v in d["versions"]} == {"AVAILABLE"}
    facts = docs.client.get(f"/api/document-versions/{version_id}/facts", headers=BUREAU).json()
    assert facts["version_status"] == "AVAILABLE" and facts["scan_status"] == "clean"
