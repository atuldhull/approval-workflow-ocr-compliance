"""The generated Cerbos policies must decide exactly like the local engine.

Needs a running Cerbos with infra/cerbos/policies loaded:
    docker compose --profile security up -d cerbos
    CERBOS_TEST_URL=http://localhost:3592 python -m pytest backend/tests/test_cerbos_parity.py
"""
import itertools
import os
from uuid import UUID

import pytest

from app.platform import policy
from app.platform.auth import CerbosAuthz
from contracts.enums import Role
from contracts.errors import Forbidden
from contracts.types import Principal, ResourceRef

URL = os.environ.get("CERBOS_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set CERBOS_TEST_URL to compare against a running Cerbos")

A, B = UUID(int=1), UUID(int=2)
REC = UUID(int=99)
PRINCIPALS = [
    Principal(UUID(int=10), Role.INSTITUTION, None, A),
    Principal(UUID(int=11), Role.RO_OFFICER, "Southern"),
    Principal(UUID(int=12), Role.SCRUTINY_COMMITTEE),
    Principal(UUID(int=13), Role.BUREAU_OFFICER),
    Principal(UUID(int=14), Role.BUREAU_HEAD),
    Principal(UUID(int=15), Role.AUDITOR),
]
RESOURCES = [
    ResourceRef(kind, rid, owner, region)
    for kind in sorted(policy.KINDS)
    for rid, owner, region in [(None, None, None), (None, None, "Southern"), (REC, A, "Southern"),
                               (REC, B, "Northern"), (REC, None, None), (None, A, None)]
]


def test_cerbos_matches_local_policy():
    cerbos = CerbosAuthz(URL)
    mismatches = []
    for p, action, r in itertools.product(PRINCIPALS, sorted(policy.POLICY), RESOURCES):
        local = policy.decide(p, action, r, demo_mode=True) is None
        try:
            cerbos.check(p, action, r)
            remote = True
        except Forbidden:
            remote = False
        if local != remote:
            mismatches.append((p.role, action, r, local, remote))
    assert mismatches == [], mismatches[:10]
