"""Fail-closed checks for the disposable database used by destructive tests."""

import re

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

DISPOSABLE_TEST_DATABASE = "awoc_test"
# awoc_test, or awoc_test_<suffix> for parallel runs (one database per branch or worker): lowercase letters and
# digits, words joined by single underscores. The name is one layer only; the local host and the explicit
# confirmation below are required as well.
_DISPOSABLE_NAME = re.compile(r"awoc_test(?:_[a-z0-9]+){0,4}")
_MAX_NAME_LENGTH = 63  # PostgreSQL identifier limit
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
        "PostgreSQL database named 'awoc_test' or 'awoc_test_<suffix>' (localhost, 127.0.0.1, "
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
        or not is_disposable_test_database_name(url.database)
        or (url.host or "").casefold() not in _LOCAL_POSTGRES_HOSTS
        or bool(url.query)
    ):
        raise UnsafeTestDatabaseConfiguration(guidance)
    return url


def is_disposable_test_database_name(name: str | None) -> bool:
    return (isinstance(name, str) and len(name) <= _MAX_NAME_LENGTH
            and _DISPOSABLE_NAME.fullmatch(name) is not None)


def is_test_cleanup_table(schema: str, table: str) -> bool:
    """Keep migration state and immutable calendar source rows during test cleanup."""
    return (schema, table) not in _PRESERVED_TEST_TABLES
