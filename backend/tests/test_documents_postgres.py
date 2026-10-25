"""PostgreSQL migration/constraint checks; the shared fixture is destructive and guarded.

These tests require the explicitly disposable awoc_test database and are never
run by database-free validation.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.platform.db import get_engine


def _insert_application(connection, institution_id, application_id):
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    connection.execute(
        text("INSERT INTO wf.institution (id, name, ro_region, is_demo) VALUES (:id, 'Synthetic', 'NORTH', true)"),
        {"id": institution_id},
    )
    connection.execute(
        text(
            "INSERT INTO wf.application (id, institution_id, category, academic_year, status, created_at) "
            "VALUES (:id, :institution_id, 'NEW_INSTITUTION', '2026-27', 'DRAFT', :created_at)"
        ),
        {"id": application_id, "institution_id": institution_id, "created_at": now},
    )


def _insert_document(
    connection,
    document_id,
    application_id,
    institution_id,
    version_id,
    digest,
    storage_ref,
    *,
    status="QUARANTINED",
):
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    connection.execute(
        text(
            "INSERT INTO doc.document (document_id, application_id, institution_id, created_at, updated_at) "
            "VALUES (:document_id, :application_id, :institution_id, :created_at, :updated_at)"
        ),
        {
            "document_id": document_id,
            "application_id": application_id,
            "institution_id": institution_id,
            "created_at": now,
            "updated_at": now,
        },
    )
    connection.execute(
        text(
            "INSERT INTO doc.document_version (document_version_id, document_id, application_id, institution_id, "
            "version_no, original_filename, media_type, size_bytes, sha256, storage_ref, status, uploaded_by, "
            "created_at, updated_at) VALUES (:version_id, :document_id, :application_id, :institution_id, 1, "
            "'sample.pdf', 'application/pdf', 8, :sha256, :storage_ref, :status, :uploaded_by, :created_at, :updated_at)"
        ),
        {
            "version_id": version_id,
            "document_id": document_id,
            "application_id": application_id,
            "institution_id": institution_id,
            "sha256": digest,
            "storage_ref": storage_ref,
            "status": status,
            "uploaded_by": uuid4(),
            "created_at": now,
            "updated_at": now,
        },
    )


def _storage_ref(institution_id, application_id, digest, operation_id=None):
    from uuid import uuid4

    operation_id = operation_id or uuid4()
    return f"quarantine/{institution_id}/{application_id}/sha256/{digest}/{operation_id}"


def test_source_metadata_is_immutable_and_availability_is_disabled(database):
    institution_id, application_id = uuid4(), uuid4()
    document_id, version_id = uuid4(), uuid4()
    digest = "a" * 64
    with get_engine().begin() as connection:
        _insert_application(connection, institution_id, application_id)

        # An AVAILABLE row is rejected by the database CHECK constraint.
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                _insert_document(
                    connection,
                    uuid4(),
                    application_id,
                    institution_id,
                    uuid4(),
                    digest,
                    _storage_ref(institution_id, application_id, digest),
                    status="AVAILABLE",
                )

        _insert_document(
            connection,
            document_id,
            application_id,
            institution_id,
            version_id,
            digest,
            _storage_ref(institution_id, application_id, digest),
        )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE doc.document SET created_at = created_at + interval '1 second' WHERE document_id = :id"),
                    {"id": document_id},
                )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE doc.document_version SET sha256 = :sha WHERE document_version_id = :id"),
                    {"sha": "b" * 64, "id": version_id},
                )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE doc.document_version SET status = 'AVAILABLE' WHERE document_version_id = :id"),
                    {"id": version_id},
                )

        status = connection.scalar(
            text("SELECT status FROM doc.document_version WHERE document_version_id = :id"), {"id": version_id}
        )
        assert status == "QUARANTINED"
        connection.execute(
            text("UPDATE doc.document_version SET status = 'REJECTED' WHERE document_version_id = :id"),
            {"id": version_id},
        )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE doc.document_version SET status = 'QUARANTINED' WHERE document_version_id = :id"),
                    {"id": version_id},
                )


def test_document_institution_must_own_application(database):
    institution_id, application_id = uuid4(), uuid4()
    wrong_institution_id = uuid4()
    with get_engine().begin() as connection:
        _insert_application(connection, institution_id, application_id)
        connection.execute(
            text("INSERT INTO wf.institution (id, name, ro_region, is_demo) VALUES (:id, 'Other', 'SOUTH', true)"),
            {"id": wrong_institution_id},
        )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                _insert_document(
                    connection,
                    uuid4(),
                    application_id,
                    wrong_institution_id,
                    uuid4(),
                    "d" * 64,
                    _storage_ref(wrong_institution_id, application_id, "d" * 64),
                )

        document_id = uuid4()
        _insert_document(
            connection,
            document_id,
            application_id,
            institution_id,
            uuid4(),
            "f" * 64,
            _storage_ref(institution_id, application_id, "f" * 64),
        )
        other_application_id = uuid4()
        connection.execute(
            text(
                "INSERT INTO wf.application (id, institution_id, category, academic_year, status, created_at) "
                "VALUES (:id, :institution_id, 'NEW_INSTITUTION', '2026-27', 'DRAFT', :created_at)"
            ),
            {
                "id": other_application_id,
                "institution_id": institution_id,
                "created_at": datetime(2026, 10, 25, tzinfo=timezone.utc),
            },
        )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE doc.document SET application_id = :application_id WHERE document_id = :id"),
                    {"application_id": other_application_id, "id": document_id},
                )


def test_document_and_version_rows_cannot_be_deleted_or_truncated(database):
    institution_id, application_id = uuid4(), uuid4()
    document_id, version_id = uuid4(), uuid4()
    with get_engine().begin() as connection:
        _insert_application(connection, institution_id, application_id)
        _insert_document(
            connection,
            document_id,
            application_id,
            institution_id,
            version_id,
            "e" * 64,
            _storage_ref(institution_id, application_id, "e" * 64),
        )
        for statement, parameters in (
            ("DELETE FROM doc.document_version WHERE document_version_id = :id", {"id": version_id}),
            ("DELETE FROM doc.document WHERE document_id = :id", {"id": document_id}),
            ("TRUNCATE doc.document_version", {}),
            ("TRUNCATE doc.document CASCADE", {}),
        ):
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(text(statement), parameters)


def test_scoped_hash_constraint_allows_same_bytes_only_in_other_application(database):
    institution_id, application_a, application_b = uuid4(), uuid4(), uuid4()
    digest = "c" * 64
    with get_engine().begin() as connection:
        _insert_application(connection, institution_id, application_a)
        _insert_application(connection, institution_id, application_b)
        doc_a, version_a = uuid4(), uuid4()
        _insert_document(
            connection,
            doc_a,
            application_a,
            institution_id,
            version_a,
            digest,
            _storage_ref(institution_id, application_a, digest),
        )
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                _insert_document(
                    connection,
                    uuid4(),
                    application_a,
                    institution_id,
                    uuid4(),
                    digest,
                    _storage_ref(institution_id, application_a, digest),
                )
        _insert_document(
            connection,
            uuid4(),
            application_b,
            institution_id,
            uuid4(),
            digest,
            _storage_ref(institution_id, application_b, digest),
        )
