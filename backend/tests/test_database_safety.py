import pytest

from scripts.database_safety import (
    UnsafeTestDatabaseConfiguration,
    is_test_cleanup_table,
    validate_disposable_test_database,
)

SAFE_URL = "postgresql+psycopg://localhost:5432/awoc_test"


def test_explicit_local_disposable_test_database_is_accepted():
    url = validate_disposable_test_database(SAFE_URL, confirmation="1")

    assert url.get_backend_name() == "postgresql"
    assert url.host == "localhost"
    assert url.database == "awoc_test"


@pytest.mark.parametrize(
    "database_url",
    [
        None,
        "",
        "not-a-database-url",
        "sqlite:///awoc_test",
        "postgresql+psycopg://localhost:5432/awoc",
        "postgresql+psycopg://localhost:5432/awoc_testing",
        "postgresql+psycopg://shared-db.example:5432/awoc_test",
        "postgresql+psycopg://shared-db.example:5432/awoc_test_p1",
        "postgresql+psycopg://localhost:5432/awoc_test?host=shared-db.example",
        "postgresql+psycopg://localhost:5432/awoc_test_p1?host=shared-db.example",
    ],
)
def test_unsafe_or_ambiguous_database_urls_are_rejected(database_url):
    with pytest.raises(UnsafeTestDatabaseConfiguration, match="Refusing destructive test database reset"):
        validate_disposable_test_database(database_url, confirmation="1")


@pytest.mark.parametrize("name", ["awoc_test", "awoc_test_p1", "awoc_test_p2", "awoc_test_worker_3"])
def test_suffixed_test_databases_are_accepted_for_parallel_runs(name):
    url = validate_disposable_test_database(f"postgresql+psycopg://localhost:5432/{name}", confirmation="1")
    assert url.database == name


@pytest.mark.parametrize("name", [
    "awoc_testing", "awoc_test_", "awoc_test__p1", "awoc_test_P1", "AWOC_TEST", "awoc_test-p1", "awoc_test_p1;x",
    "xawoc_test", "awoc_test_a_b_c_d_e", "awoc_test_" + "a" * 60,
])
def test_names_that_only_resemble_the_test_database_are_rejected(name):
    with pytest.raises(UnsafeTestDatabaseConfiguration):
        validate_disposable_test_database(f"postgresql+psycopg://localhost:5432/{name}", confirmation="1")


def test_a_suffixed_name_still_needs_the_confirmation():
    with pytest.raises(UnsafeTestDatabaseConfiguration, match="AWOC_TEST_DATABASE_DISPOSABLE=1"):
        validate_disposable_test_database("postgresql+psycopg://localhost:5432/awoc_test_p1", confirmation=None)


def test_disposable_database_requires_explicit_confirmation():
    with pytest.raises(UnsafeTestDatabaseConfiguration, match="AWOC_TEST_DATABASE_DISPOSABLE=1"):
        validate_disposable_test_database(SAFE_URL, confirmation=None)


@pytest.mark.parametrize(
    ("schema", "table"),
    [("dl", "calendar_version"), ("dl", "holiday"), ("public", "alembic_version")],
)
def test_test_cleanup_preserves_immutable_calendar_data_and_migration_state(schema, table):
    assert is_test_cleanup_table(schema, table) is False


def test_test_cleanup_includes_ordinary_application_tables():
    assert is_test_cleanup_table("dl", "deadline") is True
    assert is_test_cleanup_table("wf", "application") is True


def test_application_code_never_sets_the_test_reset_switch():
    """awoc.test_reset unlocks document-history TRUNCATE; only conftest.py's reset may set it."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    offenders = [
        str(path.relative_to(root))
        for folder in ("backend/app", "generator", "scripts")
        for path in (root / folder).rglob("*.py")
        if "awoc.test_reset" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
