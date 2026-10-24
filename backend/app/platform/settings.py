import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    demo_mode: bool
    demo_auth: bool
    rulesets_dir: Path
    contracts_dir: Path
    default_ruleset: str


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "postgresql+psycopg://awoc:awoc@localhost:5432/awoc"),
        demo_mode=_flag("DEMO_MODE", "true"),
        demo_auth=_flag("DEMO_AUTH", "true"),
        rulesets_dir=Path(os.environ.get("RULESETS_DIR", REPO_ROOT / "rulesets")),
        contracts_dir=REPO_ROOT / "contracts",
        default_ruleset=os.environ.get("DEFAULT_RULESET", "aph-2024-27@r1"),
    )


settings = load_settings()
