"""Standalone CLI against its own disposable database; no in-process test fakes."""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import create_engine, text


def test_verifier_cli_real_replay_and_existing_seed_refusal(database, tmp_path):
    name = "p1_cli_" + uuid4().hex + "_verify"
    admin = create_engine(database.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    env = dict(os.environ, DATABASE_URL=database.set(database=name).render_as_string(hide_password=False),
               DEMO_MODE="true", DEMO_AUTH="true")
    root = Path(__file__).resolve().parents[2]
    try:
        subprocess.run([sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "heads"],
                       cwd=root, env=env, check=True, capture_output=True, text=True)
        args = [sys.executable, "-m", "generator.cases.verify_answer_key", "--seed", "1",
                "--institutions", "9", "--applications", "22", "--out", str(tmp_path / "verified")]
        first = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True)
        assert first.returncode == 0, first.stdout + first.stderr
        result = json.loads((tmp_path / "verified/verification.json").read_text())
        assert result["mismatch_count"] == 0 and result["status"] == "PASS"
        assert result["counts"]["applications"] == 22
        assert json.loads((tmp_path / "verified/answer_key.json").read_text())["p2_extensions"] == {}
        repeated = subprocess.run(args[:-1] + [str(tmp_path / "repeat")], cwd=root, env=env, capture_output=True, text=True)
        assert repeated.returncode == 2 and "seed already exists" in repeated.stdout
    finally:
        # Delete only the unique database this test successfully created above.
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
