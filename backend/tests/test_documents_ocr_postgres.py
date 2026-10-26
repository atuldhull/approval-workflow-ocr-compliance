"""PostgreSQL checks for OCR-run, provenance, and review-order constraints.

Uses the repository's guarded, destructive `database` fixture. Do not run this
module unless DATABASE_URL has been verified to target disposable awoc_test.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.platform.db import get_engine


NOW = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)


def _seed_version(connection):
    institution_id, application_id = uuid4(), uuid4()
    document_id, version_id = uuid4(), uuid4()
    digest = uuid4().hex + uuid4().hex
    connection.execute(
        text("INSERT INTO wf.institution (id, name, ro_region, is_demo) VALUES (:id, 'OCR fixture', 'NORTH', true)"),
        {"id": institution_id},
    )
    connection.execute(
        text(
            "INSERT INTO wf.application (id, institution_id, category, academic_year, status, created_at) "
            "VALUES (:id, :institution_id, 'NEW_INSTITUTION', '2026-27', 'DRAFT', :now)"
        ),
        {"id": application_id, "institution_id": institution_id, "now": NOW},
    )
    connection.execute(
        text(
            "INSERT INTO doc.document (document_id, application_id, institution_id, created_at, updated_at) "
            "VALUES (:document_id, :application_id, :institution_id, :now, :now)"
        ),
        {"document_id": document_id, "application_id": application_id, "institution_id": institution_id, "now": NOW},
    )
    connection.execute(
        text(
            "INSERT INTO doc.document_version (document_version_id, document_id, application_id, institution_id, "
            "version_no, original_filename, media_type, size_bytes, sha256, storage_ref, status, uploaded_by, "
            "created_at, updated_at) VALUES (:version_id, :document_id, :application_id, :institution_id, 1, "
            "'ocr-fixture.pdf', 'application/pdf', 8, :sha, :storage_ref, 'QUARANTINED', :uploaded_by, :now, :now)"
        ),
        {
            "version_id": version_id,
            "document_id": document_id,
            "application_id": application_id,
            "institution_id": institution_id,
            "sha": digest,
            "storage_ref": f"quarantine/{institution_id}/{application_id}/{digest}",
            "uploaded_by": uuid4(),
            "now": NOW,
        },
    )
    return document_id, version_id


def _insert_run(connection, version_id, run_id=None):
    run_id = run_id or uuid4()
    connection.execute(
        text(
            "INSERT INTO doc.ocr_run (ocr_run_id, document_version_id, adapter_key, model_version, "
            "status, attempt_number, created_at) VALUES (:run_id, :version_id, 'test.fake', 'fixture-1', "
            "'QUEUED', 1, :now)"
        ),
        {"run_id": run_id, "version_id": version_id, "now": NOW},
    )
    return run_id


def _insert_fact(connection, run_id, version_id, *, fact_id=None, state="PROPOSED"):
    fact_id = fact_id or uuid4()
    connection.execute(
        text(
            "INSERT INTO doc.fact (fact_id, ocr_run_id, document_version_id, field_key, candidate_text, "
            "normalized_value, normalization_status, script_code, confidence, page_number, source_span_start, "
            "source_span_end, state, created_at) VALUES (:fact_id, :run_id, :version_id, 'issue_date', "
            "'२०२५-०३-१२', '2025-03-12', 'NORMALIZED', 'DEVANAGARI', 0.01000, 1, 0, 10, :state, :now)"
        ),
        {"fact_id": fact_id, "run_id": run_id, "version_id": version_id, "state": state, "now": NOW},
    )
    return fact_id


def test_ocr_run_requires_failed_parent_for_single_retry(database):
    with get_engine().begin() as connection:
        _, version_id = _seed_version(connection)
        run_id = _insert_run(connection, version_id)

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO doc.ocr_run (ocr_run_id, document_version_id, adapter_key, model_version, "
                        "status, attempt_number, retry_of_ocr_run_id, created_at) VALUES (:id, :version, 'test.fake', "
                        "'fixture-1', 'QUEUED', 2, :parent, :now)"
                    ),
                    {
                        "id": uuid4(),
                        "version": version_id,
                        "parent": run_id,
                        "now": NOW + timedelta(seconds=1),
                    },
                )

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE doc.ocr_run SET status='SUCCEEDED', started_at=:start, finished_at=:finish WHERE ocr_run_id=:id"),
                    {"start": NOW + timedelta(seconds=1), "finish": NOW + timedelta(seconds=2), "id": run_id},
                )

        connection.execute(
            text("UPDATE doc.ocr_run SET status='FAILED', error_code='TIMEOUT', finished_at=:finish WHERE ocr_run_id=:id"),
            {"finish": NOW + timedelta(seconds=1), "id": run_id},
        )
        retry_id = uuid4()
        connection.execute(
            text(
                "INSERT INTO doc.ocr_run (ocr_run_id, document_version_id, adapter_key, model_version, status, "
                "attempt_number, retry_of_ocr_run_id, created_at) VALUES (:id, :version, 'test.fake', 'fixture-1', "
                "'QUEUED', 2, :parent, :now)"
            ),
            {"id": retry_id, "version": version_id, "parent": run_id, "now": NOW + timedelta(seconds=2)},
        )
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO doc.ocr_run (ocr_run_id, document_version_id, adapter_key, model_version, "
                        "status, attempt_number, retry_of_ocr_run_id, created_at) VALUES (:id, :version, 'test.fake', "
                        "'fixture-1', 'QUEUED', 2, :parent, :now)"
                    ),
                    {"id": uuid4(), "version": version_id, "parent": run_id, "now": NOW + timedelta(seconds=3)},
                )


def test_ocr_retry_cannot_cross_document_versions(database):
    with get_engine().begin() as connection:
        document_id, version_a = _seed_version(connection)
        owner = connection.execute(
            text("SELECT application_id, institution_id FROM doc.document WHERE document_id=:id"),
            {"id": document_id},
        ).one()
        version_b = uuid4()
        digest = uuid4().hex + uuid4().hex
        connection.execute(
            text(
                "INSERT INTO doc.document_version (document_version_id, document_id, application_id, institution_id, "
                "version_no, original_filename, media_type, size_bytes, sha256, storage_ref, status, uploaded_by, "
                "created_at, updated_at) VALUES (:version, :document, :application, :institution, 2, 'v2.pdf', "
                "'application/pdf', 8, :sha, :ref, 'QUARANTINED', :uploaded_by, :now, :now)"
            ),
            {
                "version": version_b,
                "document": document_id,
                "application": owner.application_id,
                "institution": owner.institution_id,
                "sha": digest,
                "ref": f"quarantine/{owner.institution_id}/{owner.application_id}/{digest}",
                "uploaded_by": uuid4(),
                "now": NOW,
            },
        )
        parent_id = _insert_run(connection, version_a)
        connection.execute(
            text("UPDATE doc.ocr_run SET status='FAILED', error_code='TIMEOUT', finished_at=:finish WHERE ocr_run_id=:id"),
            {"finish": NOW + timedelta(seconds=1), "id": parent_id},
        )

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO doc.ocr_run (ocr_run_id, document_version_id, adapter_key, model_version, "
                        "status, attempt_number, retry_of_ocr_run_id, created_at) VALUES (:id, :version, 'test.fake', "
                        "'fixture-1', 'QUEUED', 2, :parent, :now)"
                    ),
                    {
                        "id": uuid4(),
                        "version": version_b,
                        "parent": parent_id,
                        "now": NOW + timedelta(seconds=2),
                    },
                )


def test_quarantined_version_cannot_start_ocr_or_persist_facts(database):
    with get_engine().begin() as connection:
        _, version_id = _seed_version(connection)
        run_id = _insert_run(connection, version_id)
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE doc.document_version SET status='AVAILABLE' WHERE document_version_id=:id"),
                    {"id": version_id},
                )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE doc.ocr_run SET status='RUNNING', started_at=:now WHERE ocr_run_id=:id"),
                    {"now": NOW + timedelta(seconds=1), "id": run_id},
                )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE doc.ocr_run SET adapter_key='other.adapter' WHERE ocr_run_id=:id"),
                    {"id": run_id},
                )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                _insert_fact(connection, run_id, version_id)
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                _insert_fact(connection, run_id, version_id, state="CONFIRMED")
        status = connection.execute(
            text("SELECT status FROM doc.document_version WHERE document_version_id=:id"), {"id": version_id}
        ).scalar_one()
        assert status == "QUARANTINED"


def test_fact_insert_rejects_run_and_version_provenance_mismatch(database):
    with get_engine().begin() as connection:
        document_id, version_a = _seed_version(connection)
        version_b = uuid4()
        digest = uuid4().hex + uuid4().hex
        owner = connection.execute(
            text("SELECT application_id, institution_id FROM doc.document WHERE document_id=:id"),
            {"id": document_id},
        ).one()
        connection.execute(
            text(
                "INSERT INTO doc.document_version (document_version_id, document_id, application_id, institution_id, "
                "version_no, original_filename, media_type, size_bytes, sha256, storage_ref, status, uploaded_by, "
                "created_at, updated_at) VALUES (:version, :document, :application, :institution, 2, 'v2.pdf', "
                "'application/pdf', 8, :sha, :ref, 'QUARANTINED', :uploaded_by, :now, :now)"
            ),
            {
                "version": version_b,
                "document": document_id,
                "application": owner.application_id,
                "institution": owner.institution_id,
                "sha": digest,
                "ref": f"quarantine/{owner.institution_id}/{owner.application_id}/{digest}",
                "uploaded_by": uuid4(),
                "now": NOW,
            },
        )
        run_id = _insert_run(connection, version_a)
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                _insert_fact(connection, run_id, version_b)


_DOCUMENT_HISTORY_TABLES = ("document", "document_version", "ocr_run", "fact")


def test_all_document_history_tables_have_before_delete_row_guards(database):
    expected_trigger_names = {
        "document": "trg_doc_document_no_delete",
        "document_version": "trg_doc_document_version_no_delete",
        "ocr_run": "trg_doc_ocr_run_no_delete",
        "fact": "trg_doc_fact_no_delete",
    }
    with get_engine().begin() as connection:
        rows = connection.execute(
            text(
                "SELECT c.relname AS table_name, t.tgname, t.tgtype "
                "FROM pg_trigger AS t "
                "JOIN pg_class AS c ON c.oid = t.tgrelid "
                "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'doc' AND NOT t.tgisinternal"
            )
        ).mappings().all()

    actual = {row["table_name"]: row for row in rows if row["tgname"] in expected_trigger_names.values()}
    assert set(actual) == set(expected_trigger_names)
    for table_name, trigger_name in expected_trigger_names.items():
        trigger = actual[table_name]
        assert trigger["tgname"] == trigger_name
        # PostgreSQL trigger flags: ROW=1, BEFORE=2, DELETE=8.
        assert trigger["tgtype"] & 1
        assert trigger["tgtype"] & 2
        assert trigger["tgtype"] & 8


@pytest.mark.parametrize("table_name", _DOCUMENT_HISTORY_TABLES)
def test_delete_is_rejected_for_each_document_history_table(database, table_name):
    # The statement guard also rejects a no-op DELETE when the table has no
    # rows; row-level guards independently protect every persisted row.
    with get_engine().begin() as connection:
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(text(f"DELETE FROM doc.{table_name}"))


@pytest.mark.parametrize("table_name", _DOCUMENT_HISTORY_TABLES)
@pytest.mark.parametrize(
    "test_reset_value",
    (None, "", "true"),
    ids=("setting-absent", "setting-empty", "setting-not-on"),
)
def test_truncate_is_rejected_unless_test_reset_is_exactly_on(database, table_name, test_reset_value):
    with get_engine().begin() as connection:
        if test_reset_value is None:
            # PostgreSQL may expose an unset custom GUC as NULL or as the
            # empty reset placeholder after a prior transaction-local SET.
            assert connection.scalar(text("SELECT current_setting('awoc.test_reset', true)")) in (None, "")
        else:
            configured = connection.scalar(
                text("SELECT set_config('awoc.test_reset', :value, true)"),
                {"value": test_reset_value},
            )
            assert configured == test_reset_value

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(text(f"TRUNCATE TABLE doc.{table_name} CASCADE"))


def test_truncate_is_allowed_only_inside_controlled_test_reset_transaction(database):
    with get_engine().begin() as connection:
        counts_before = {
            table_name: connection.scalar(text(f"SELECT count(*) FROM doc.{table_name}"))
            for table_name in _DOCUMENT_HISTORY_TABLES
        }
        reset_transaction = connection.begin_nested()
        try:
            configured = connection.scalar(
                text("SELECT set_config('awoc.test_reset', 'on', true)")
            )
            assert configured == "on"
            connection.execute(
                text(
                    "TRUNCATE TABLE doc.document, doc.document_version, doc.ocr_run, doc.fact CASCADE"
                )
            )
        finally:
            # PostgreSQL TRUNCATE is transactional; rolling back this savepoint
            # keeps the test reset isolated and restores any preexisting rows.
            reset_transaction.rollback()

        # Rolling back the savepoint removes the local value; PostgreSQL may
        # report that reset custom GUC as NULL or an empty string.
        assert connection.scalar(text("SELECT current_setting('awoc.test_reset', true)")) in (None, "")
        counts_after = {
            table_name: connection.scalar(text(f"SELECT count(*) FROM doc.{table_name}"))
            for table_name in _DOCUMENT_HISTORY_TABLES
        }
        assert counts_after == counts_before
