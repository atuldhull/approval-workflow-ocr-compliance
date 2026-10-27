"""Idempotent commands, exercised with the real application-creation service and the real ledger.

The HTTP route here is test-only: it wires Person 1's service through the platform helper exactly as
docs/IDEMPOTENCY.md proposes for POST /applications, without changing Person 1's module.
"""
import threading
import time
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.deadlines.wiring import clock
from app.intake import service
from app.intake.api import ApplicationIn, _out
from app.platform.auth import current_principal
from app.platform.db import new_session, unit_of_work
from app.platform.idempotency import (IdempotencyStore, fingerprint, idempotency_key, idempotent_response,
                                      purge_expired, run_idempotent)
from app.platform.models import DomainEvent, IdempotencyRecord
from conftest import SUNRISE, headers
from contracts.enums import Role
from contracts.errors import Conflict
from contracts.types import Principal

INST = headers("INSTITUTION", SUNRISE)
PRINCIPAL = Principal(UUID(INST["X-Demo-User"]), Role.INSTITUTION, None, SUNRISE)
BODY = {"institution_id": str(SUNRISE), "category": "NEW_PROGRAMME", "academic_year": "2027-28"}
ROUTE = "/applications"


def mount(client: TestClient) -> TestClient:
    router = APIRouter()

    @router.post("/_test/applications", status_code=201)
    def create(body: ApplicationIn, principal: Principal = Depends(current_principal),
               key: str | None = Depends(idempotency_key)):
        return idempotent_response(
            principal, key, "POST", ROUTE, {}, body.model_dump(mode="json"),
            lambda uow: service.create_application(uow, body.institution_id, body.category, body.academic_year),
            lambda a: _out(a).model_dump(mode="json"), status_code=201)

    client.app.include_router(router, prefix="/api")
    return client


@pytest.fixture
def api(client):
    return mount(client)


def post(api, key, body=BODY, h=INST):
    extra = {"Idempotency-Key": key} if key else {}
    return api.post("/api/_test/applications", headers={**h, **extra}, json=body)


def count_created():
    with new_session() as s:
        return s.scalar(select(func.count()).select_from(DomainEvent)
                        .where(DomainEvent.event_type == "wf.application_created"))


def test_identical_retry_returns_the_original_result_and_does_nothing_twice(api):
    first = post(api, "key-00000001")
    again = post(api, "key-00000001")
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json()
    assert again.headers["Idempotent-Replayed"] == "true" and "Idempotent-Replayed" not in first.headers
    assert count_created() == 1


def test_without_a_key_every_request_runs(api):
    post(api, None)
    post(api, None)
    assert count_created() == 2


def test_reusing_a_key_for_a_different_request_is_refused(api):
    post(api, "key-00000002")
    r = post(api, "key-00000002", body={**BODY, "category": "INCREASE_INTAKE"})
    assert r.status_code == 422 and "different request" in r.text
    assert count_created() == 1


def test_malformed_keys_are_rejected(api):
    assert post(api, "short").status_code == 422
    assert post(api, "has spaces in it").status_code == 422


def test_keys_are_scoped_to_the_user(api):
    other_user = headers("INSTITUTION", SUNRISE, user="00000000-0000-4000-9000-000000000099")
    a = post(api, "shared-key-0001")
    b = post(api, "shared-key-0001", h=other_user)
    assert a.json()["id"] != b.json()["id"]
    assert count_created() == 2


def test_result_survives_a_restart(api):
    first = post(api, "key-00000003")
    from app.main import create_app
    from app.platform.db import get_engine
    get_engine().dispose()                       # drop every pooled connection, like a process restart
    restarted = mount(TestClient(create_app()))
    again = post(restarted, "key-00000003")
    assert again.json() == first.json() and again.headers["Idempotent-Replayed"] == "true"
    assert count_created() == 1


def test_failed_command_leaves_no_trace_and_can_be_retried(api, monkeypatch):
    real = service.create_application

    def fails_after_writing(uow, *args):
        real(uow, *args)                          # application row + ledger event written...
        raise Conflict("simulated failure")       # ...then the command fails

    monkeypatch.setattr(service, "create_application", fails_after_writing)
    assert post(api, "key-00000004").status_code == 409
    with new_session() as s:
        assert s.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
    assert count_created() == 0

    monkeypatch.setattr(service, "create_application", real)
    assert post(api, "key-00000004").status_code == 201
    assert count_created() == 1


def test_expired_keys_no_longer_replay(api):
    first = post(api, "key-00000005")
    clock.advance(2)                              # retention is 24 hours
    again = post(api, "key-00000005")
    assert again.status_code == 201 and again.json()["id"] != first.json()["id"]
    assert "Idempotent-Replayed" not in again.headers


def test_purge_removes_only_expired_records(api):
    post(api, "key-00000006")
    clock.advance(2)
    post(api, "key-00000007")
    with new_session() as s:
        assert purge_expired(s) == 1
        s.commit()
        assert s.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1


def test_concurrent_identical_requests_run_the_command_once(client):
    barrier = threading.Barrier(2)
    results = []

    def command(uow):
        app = service.create_application(uow, SUNRISE, "NEW_PROGRAMME", "2027-28")
        time.sleep(0.5)                           # keep the first transaction open while the second arrives
        return app

    def worker():
        barrier.wait()
        results.append(run_idempotent(PRINCIPAL, "race-key-0001", "POST", ROUTE, fingerprint({}, BODY), command,
                                      lambda a: {"id": str(a.id)}, 201))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 2
    assert results[0][1] == results[1][1]                  # same application id
    assert sorted(r[2] for r in results) == [False, True]  # one ran, one replayed
    assert count_created() == 1


def test_a_request_stuck_behind_a_long_one_gets_409(client):
    holder = IdempotencyStore()
    waiter = IdempotencyStore(lock_timeout_ms=200)
    with unit_of_work(PRINCIPAL) as uow:
        assert holder.claim(uow, "slow-key-0001", "POST", ROUTE, "h") is None   # claimed, not committed yet
        outcome = []

        def second():
            try:
                with unit_of_work(PRINCIPAL) as uow2:
                    waiter.claim(uow2, "slow-key-0001", "POST", ROUTE, "h")
            except Conflict as e:
                outcome.append(e)

        t = threading.Thread(target=second)
        t.start()
        t.join()
        uow.session.rollback()
    assert outcome and "still being processed" in str(outcome[0])


def test_stored_records_hold_no_headers_or_raw_key(api):
    post(api, "secret-looking-key-0001")
    with new_session() as s:
        rec = s.scalars(select(IdempotencyRecord)).one()
    assert rec.key_hash != "secret-looking-key-0001" and len(rec.key_hash) == 64
    assert "X-Demo" not in str(rec.response_body)
