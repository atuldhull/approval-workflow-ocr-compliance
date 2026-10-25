"""Fail-closed checks for the disposable database used by destructive tests."""

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

DISPOSABLE_TEST_DATABASE = "awoc_test"
DISPOSABLE_TEST_CONFIRMATION = "AWOC_TEST_DATABASE_DISPOSABLE"
_LOCAL_POSTGRES_HOSTS = {"localhost", "127.0.0.1", "::1"}
_PRESERVED_TEST_TABLES = {
    ("dl", "calendar_version"),
    ("dl", "holiday"),
    ("public", "alembic_version"),
}


class UnsafeTestDatabaseConfiguration(ValueError):
    """Raised before a test fixture can drop an unverified database."""


def validate_disposable_test_database(
    database_url: str | None, *, confirmation: str | None
) -> URL:
    """Accept only explicit, local PostgreSQL test-database configuration."""
    guidance = (
        "Refusing destructive test database reset. Set DATABASE_URL to a local "
        "PostgreSQL database named exactly 'awoc_test' (localhost, 127.0.0.1, "
        "or ::1; no URL query options), and set "
        f"{DISPOSABLE_TEST_CONFIRMATION}=1 only after confirming that database "
        "is disposable. No database connection was opened."
    )
    if confirmation != "1":
        raise UnsafeTestDatabaseConfiguration(guidance)
    if not isinstance(database_url, str) or not database_url.strip():
        raise UnsafeTestDatabaseConfiguration(guidance)
    try:
        url = make_url(database_url)
    except (ArgumentError, TypeError):
        raise UnsafeTestDatabaseConfiguration(guidance) from None

    if (
        url.get_backend_name() != "postgresql"
        or url.database != DISPOSABLE_TEST_DATABASE
        or (url.host or "").casefold() not in _LOCAL_POSTGRES_HOSTS
        or bool(url.query)
    ):
        raise UnsafeTestDatabaseConfiguration(guidance)
    return url


def is_test_cleanup_table(schema: str, table: str) -> bool:
    """Keep migration state and immutable calendar source rows during test cleanup."""
    return (schema, table) not in _PRESERVED_TEST_TABLES
