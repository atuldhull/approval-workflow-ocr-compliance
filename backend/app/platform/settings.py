import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

LEASE_TIMEOUT_FACTOR = 10   # SMTP socket operations per send (~8) plus margin

ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "EdDSA"})


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _list(name: str, default: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in os.environ.get(name, default).split(",") if v.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str
    demo_mode: bool
    demo_auth: bool
    rulesets_dir: Path
    contracts_dir: Path
    default_ruleset: str
    # deployment
    app_env: str = "development"            # development | production
    # identity (used when demo_auth is false)
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_client_id: str = ""                # public browser client; never has a secret
    oidc_algorithms: tuple[str, ...] = ("RS256",)
    oidc_leeway_seconds: int = 30
    # policy
    authz_engine: str = "local"             # local | cerbos
    cerbos_url: str = ""
    cerbos_timeout_seconds: float = 2.0
    authz_require_assignment: bool = False  # refuse committee case access until assignment data exists
    # idempotency
    idempotency_ttl_hours: int = 24
    # notifications
    notify_max_attempts: int = 6
    notify_backoff_base_seconds: int = 30
    notify_backoff_cap_seconds: int = 3600
    notify_lease_seconds: int = 120
    smtp_host: str = ""
    smtp_port: int = 25
    smtp_from: str = "no-reply@awoc.example.invalid"
    smtp_starttls: bool = False
    smtp_timeout_seconds: float = 10.0      # per socket operation; one send makes about 8 of them
    notify_recipient_key: str = ""          # HMAC key for per-recipient delivery records; required in production
    # audit checkpoints
    audit_signing_key_file: str = ""        # Ed25519 private key (PEM); never committed
    audit_signing_key_id: str = ""
    audit_trusted_keys_file: str = ""       # JSON {key_id: base64 raw public key}; trusted configuration
    audit_witness_dir: str = ""             # independent copy of every checkpoint

    @property
    def auth_mode(self) -> str:
        return "demo" if self.demo_auth else "oidc"


def load_settings() -> Settings:
    issuer = os.environ.get("OIDC_ISSUER", "").rstrip("/")
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "postgresql+psycopg://awoc:awoc@localhost:5432/awoc"),
        demo_mode=_flag("DEMO_MODE", "true"),
        demo_auth=_flag("DEMO_AUTH", "true"),
        rulesets_dir=Path(os.environ.get("RULESETS_DIR", REPO_ROOT / "rulesets")),
        contracts_dir=REPO_ROOT / "contracts",
        default_ruleset=os.environ.get("DEFAULT_RULESET", "aph-2024-27@r1"),
        app_env=os.environ.get("APP_ENV", "development").strip().lower(),
        oidc_issuer=issuer,
        oidc_audience=os.environ.get("OIDC_AUDIENCE", ""),
        oidc_jwks_url=os.environ.get("OIDC_JWKS_URL", f"{issuer}/protocol/openid-connect/certs" if issuer else ""),
        oidc_client_id=os.environ.get("OIDC_CLIENT_ID", ""),
        oidc_algorithms=_list("OIDC_ALGORITHMS", "RS256"),
        oidc_leeway_seconds=_int("OIDC_LEEWAY_SECONDS", 30),
        authz_engine=os.environ.get("AUTHZ_ENGINE", "local").strip().lower(),
        cerbos_url=os.environ.get("CERBOS_URL", "").rstrip("/"),
        cerbos_timeout_seconds=float(os.environ.get("CERBOS_TIMEOUT_SECONDS", "2")),
        authz_require_assignment=_flag("AUTHZ_REQUIRE_ASSIGNMENT",
                                       "true" if os.environ.get("APP_ENV", "").strip().lower() == "production" else "false"),
        idempotency_ttl_hours=_int("IDEMPOTENCY_TTL_HOURS", 24),
        notify_max_attempts=_int("NOTIFY_MAX_ATTEMPTS", 6),
        notify_backoff_base_seconds=_int("NOTIFY_BACKOFF_BASE_SECONDS", 30),
        notify_backoff_cap_seconds=_int("NOTIFY_BACKOFF_CAP_SECONDS", 3600),
        notify_lease_seconds=_int("NOTIFY_LEASE_SECONDS", 120),
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=_int("SMTP_PORT", 25),
        smtp_from=os.environ.get("SMTP_FROM", "no-reply@awoc.example.invalid"),
        smtp_starttls=_flag("SMTP_STARTTLS", "false"),
        smtp_timeout_seconds=float(os.environ.get("SMTP_TIMEOUT_SECONDS", "10")),
        notify_recipient_key=os.environ.get("NOTIFY_RECIPIENT_KEY", ""),
        audit_signing_key_file=os.environ.get("AUDIT_SIGNING_KEY_FILE", ""),
        audit_signing_key_id=os.environ.get("AUDIT_SIGNING_KEY_ID", ""),
        audit_trusted_keys_file=os.environ.get("AUDIT_TRUSTED_KEYS_FILE", ""),
        audit_witness_dir=os.environ.get("AUDIT_WITNESS_DIR", ""),
    )


def problems(s: Settings) -> list[str]:
    """Configuration that must stop the application from starting."""
    found = []
    if s.app_env not in {"development", "production"}:
        found.append(f"APP_ENV must be development or production, not {s.app_env!r}")
    if s.app_env == "production":
        if s.demo_auth:
            found.append("DEMO_AUTH must be false in production")
        if s.demo_mode:
            found.append("DEMO_MODE must be false in production")
        if s.authz_engine != "cerbos":
            found.append("AUTHZ_ENGINE must be cerbos in production")
        if len(s.notify_recipient_key) < 32:
            found.append("NOTIFY_RECIPIENT_KEY (32+ characters) is required in production")
        if not s.authz_require_assignment:
            found.append("AUTHZ_REQUIRE_ASSIGNMENT must stay on in production until case assignments exist")
    if not s.demo_auth:
        for name, value in (("OIDC_ISSUER", s.oidc_issuer), ("OIDC_AUDIENCE", s.oidc_audience),
                            ("OIDC_JWKS_URL", s.oidc_jwks_url)):
            if not value:
                found.append(f"{name} is required when DEMO_AUTH is false")
        bad = set(s.oidc_algorithms) - ASYMMETRIC_ALGORITHMS
        if bad or not s.oidc_algorithms:
            found.append(f"OIDC_ALGORITHMS must be asymmetric signature algorithms, got {sorted(bad) or 'none'}")
        if s.app_env == "production":
            for name, value in (("OIDC_ISSUER", s.oidc_issuer), ("OIDC_JWKS_URL", s.oidc_jwks_url)):
                if value and not value.startswith("https://"):
                    found.append(f"{name} must use https in production")
    # A send that outlives the worker's lease lets another worker send the same message to the same recipient.
    if s.notify_lease_seconds < LEASE_TIMEOUT_FACTOR * s.smtp_timeout_seconds:
        found.append(f"NOTIFY_LEASE_SECONDS ({s.notify_lease_seconds}) must be at least {LEASE_TIMEOUT_FACTOR} x "
                     f"SMTP_TIMEOUT_SECONDS ({s.smtp_timeout_seconds:g}) so one send cannot outlive the lease")
    if s.authz_engine not in {"local", "cerbos"}:
        found.append(f"AUTHZ_ENGINE must be local or cerbos, not {s.authz_engine!r}")
    if s.authz_engine == "cerbos" and not s.cerbos_url:
        found.append("CERBOS_URL is required when AUTHZ_ENGINE is cerbos")
    return found


def ensure_safe(s: Settings) -> None:
    found = problems(s)
    if found:
        raise RuntimeError("unsafe configuration: " + "; ".join(found))


settings = load_settings()
