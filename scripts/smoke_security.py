"""End-to-end check of real sign-in + Cerbos against a running local stack. LOCAL DEMO ONLY.

Needs: Keycloak (realm infra/keycloak/realm-awoc.json), Cerbos, and the backend started with
DEMO_AUTH=false AUTHZ_ENGINE=cerbos (see .env.security.example).

    python scripts/smoke_security.py [--api http://localhost:8000] [--idp http://localhost:8081/realms/awoc]

Uses the `awoc-smoke` password-grant client, which exists only in the local demo realm.
"""
import argparse
import sys

import httpx

SUNRISE = "00000000-0000-4000-8000-000000000001"
DEMO_PASSWORD = "demo-only-password"  # synthetic local accounts only


def token(idp: str, username: str) -> str:
    r = httpx.post(f"{idp}/protocol/openid-connect/token", data={
        "grant_type": "password", "client_id": "awoc-smoke", "username": username, "password": DEMO_PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--idp", default="http://localhost:8081/realms/awoc")
    a = ap.parse_args()
    api = httpx.Client(base_url=f"{a.api}/api", timeout=10)
    h = {u: {"Authorization": f"Bearer {token(a.idp, u)}"} for u in
         ("inst.sunrise", "inst.northfield", "ro.southern", "auditor", "bureau.head")}

    results = []

    def expect(name, response, status):
        ok = response.status_code == status
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {response.status_code} (expected {status})")
        return response

    expect("no token", api.get("/applications"), 401)
    expect("forged demo headers", api.get("/applications", headers={"X-Demo-User": SUNRISE, "X-Demo-Role": "AUDITOR"}), 401)
    expect("tampered token", api.get("/applications", headers={"Authorization": h["inst.sunrise"]["Authorization"][:-4] + "AAAA"}), 401)
    me = expect("who am I (institution)", api.get("/auth/me", headers=h["inst.sunrise"]), 200).json()
    print("      ", me)
    created = expect("institution files its own application", api.post("/applications", headers=h["inst.sunrise"], json={
        "institution_id": SUNRISE, "category": "NEW_PROGRAMME", "academic_year": "2027-28"}), 201).json()
    app_id = created["id"]
    expect("institution submits it", api.post(f"/applications/{app_id}/submit", headers=h["inst.sunrise"]), 200)
    expect("other institution reads it", api.get(f"/applications/{app_id}", headers=h["inst.northfield"]), 403)
    expect("other institution reads its timeline", api.get(f"/cases/{app_id}/timeline", headers=h["inst.northfield"]), 403)
    expect("other institution files for it", api.post("/applications", headers=h["inst.northfield"], json={
        "institution_id": SUNRISE, "category": "NEW_PROGRAMME", "academic_year": "2027-28"}), 403)
    expect("Southern regional officer reads Southern timeline", api.get(f"/cases/{app_id}/timeline", headers=h["ro.southern"]), 200)
    expect("regional officer lists unfiltered applications", api.get("/applications", headers=h["ro.southern"]), 403)
    expect("institution verifies the ledger", api.get("/ledger/verify", headers=h["inst.sunrise"]), 403)
    expect("auditor verifies the ledger", api.get("/ledger/verify", headers=h["auditor"]), 200)
    # read-only and scoped roles cannot write, whatever the frontend shows them
    expect("auditor files an application", api.post("/applications", headers=h["auditor"], json={
        "institution_id": SUNRISE, "category": "NEW_PROGRAMME", "academic_year": "2027-28"}), 403)
    expect("regional officer submits for the institution", api.post(f"/applications/{app_id}/submit", headers=h["ro.southern"]), 403)
    expect("auditor retries a delivery", api.post(f"/notifications/outbox/{app_id}/retry", headers=h["auditor"]), 403)
    expect("token in the query string is ignored", api.get("/auth/me", params={"access_token": h["inst.sunrise"]["Authorization"][7:]}), 401)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
