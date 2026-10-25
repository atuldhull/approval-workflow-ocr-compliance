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
        "postgresql+psycopg://localhost:5432/awoc_test_staging",
        "postgresql+psycopg://shared-db.example:5432/awoc_test",
        "postgresql+psycopg://localhost:5432/awoc_test?host=shared-db.example",
    ],
)
def test_unsafe_or_ambiguous_database_urls_are_rejected(database_url):
    with pytest.raises(UnsafeTestDatabaseConfiguration, match="Refusing destructive test database reset"):
        validate_disposable_test_database(database_url, confirmation="1")


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
