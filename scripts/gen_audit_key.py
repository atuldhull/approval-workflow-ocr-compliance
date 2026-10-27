"""Creates an Ed25519 checkpoint signing key in .secrets/ (git-ignored) and adds its public half to the trusted keys.

    python scripts/gen_audit_key.py demo-2026-10

Rotation: generate a new key id, point AUDIT_SIGNING_KEY_FILE/ID at it, and keep the old public key in the trusted
keys file so earlier checkpoints still verify. Remove a public key only if that key is known to be compromised.
"""
import base64
import json
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".secrets"


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,40}", sys.argv[1]):
        print("usage: gen_audit_key.py <key-id>   (lowercase letters, digits, '-')")
        return 1
    kid = sys.argv[1]
    SECRETS.mkdir(exist_ok=True)
    private_path = SECRETS / f"audit-{kid}.pem"
    if private_path.exists():
        print(f"{private_path} already exists; choose a new key id")
        return 1
    key = Ed25519PrivateKey.generate()
    private_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
    trusted_path = SECRETS / "audit-trusted-keys.json"
    trusted = json.loads(trusted_path.read_text()) if trusted_path.exists() else {}
    trusted[kid] = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                                                                  serialization.PublicFormat.Raw)).decode()
    trusted_path.write_text(json.dumps(trusted, indent=2) + "\n")
    print(f"""created {private_path.relative_to(ROOT)} and trusted {kid} in {trusted_path.relative_to(ROOT)}

Set (paths as the backend sees them; inside Docker the folder is mounted at /srv/.secrets):
  AUDIT_SIGNING_KEY_FILE=.secrets/audit-{kid}.pem
  AUDIT_SIGNING_KEY_ID={kid}
  AUDIT_TRUSTED_KEYS_FILE=.secrets/audit-trusted-keys.json
  AUDIT_WITNESS_DIR=.secrets/witness

For a real deployment the private key belongs in a secret store and the witness outside this machine.""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
