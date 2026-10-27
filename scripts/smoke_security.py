"""End-to-end check of real sign-in + Cerbos against a running local stack. LOCAL DEMO ONLY.

Needs: Keycloak (realm infra/keycloak/realm-awoc.json), Cerbos, and the backend started with
DEMO_AUTH=false AUTHZ_ENGINE=cerbos (see .env.security.example).

    python scripts/smoke_security.py [--api http://localhost:8000] [--idp http://localhost:8081/realms/awoc]

Uses the `awoc-smoke` password-grant client, which exists only in the local demo realm. Besides sign-in and case
scoping it checks who may touch documents, letters, evidence and alerts (decided by Cerbos here), and the security
headers on API responses, refusals included. The document flow itself is in scripts/smoke_demo.py.
"""
import argparse
import sys
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx

SUNRISE = "00000000-0000-4000-8000-000000000001"
DEMO_PASSWORD = "demo-only-password"  # synthetic local accounts only
API_HEADERS = {
    "x-content-type-options": "nosniff", "x-frame-options": "DENY", "referrer-policy": "no-referrer",
    "cross-origin-resource-policy": "same-origin", "cache-control": "no-store",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
}
# never stored: every upload below is refused before the body is read
TINY_PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


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
         ("inst.sunrise", "inst.northfield", "ro.southern", "ro.northern", "auditor", "bureau.head",
                   "bureau.officer")}

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
    # Submission needs every mandatory checklist item linked. The demo realm runs with DEMO_MODE=true, where a
    # deterministic UUID5 reference stands in for a scanned document (no ClamAV needed for these checks).
    checklist = api.get(f"/applications/{app_id}/checklist", headers=h["inst.sunrise"]).json()
    items = [{"item_key": i["item_key"], "state": "PROVIDED",
              "document_ref": str(uuid5(NAMESPACE_URL, f"DEMO:smoke-security:{app_id}:{i['item_key']}"))}
             for i in checklist.get("items", []) if i["mandatory"]]
    expect("institution links its checklist items", api.post(f"/applications/{app_id}/items", headers=h["inst.sunrise"],
                                                             json={"items": items}), 200)
    expect("institution submits it", api.post(f"/applications/{app_id}/submit", headers=h["inst.sunrise"],
                                              json={"dsc_present": True}), 200)
    expect("other institution reads it", api.get(f"/applications/{app_id}", headers=h["inst.northfield"]), 403)
    expect("other institution reads its timeline", api.get(f"/cases/{app_id}/timeline", headers=h["inst.northfield"]), 403)
    expect("other institution files for it", api.post("/applications", headers=h["inst.northfield"], json={
        "institution_id": SUNRISE, "category": "NEW_PROGRAMME", "academic_year": "2027-28"}), 403)
    expect("Southern regional officer reads Southern timeline", api.get(f"/cases/{app_id}/timeline", headers=h["ro.southern"]), 200)
    expect("Northern regional officer reads Southern timeline", api.get(f"/cases/{app_id}/timeline", headers=h["ro.northern"]), 403)
    expect("regional officer lists unfiltered applications", api.get("/applications", headers=h["ro.southern"]), 403)
    expect("institution verifies the ledger", api.get("/ledger/verify", headers=h["inst.sunrise"]), 403)
    expect("auditor verifies the ledger", api.get("/ledger/verify", headers=h["auditor"]), 200)
    # read-only and scoped roles cannot write, whatever the frontend shows them
    expect("auditor files an application", api.post("/applications", headers=h["auditor"], json={
        "institution_id": SUNRISE, "category": "NEW_PROGRAMME", "academic_year": "2027-28"}), 403)
    expect("regional officer submits for the institution", api.post(f"/applications/{app_id}/submit", headers=h["ro.southern"]), 403)
    expect("auditor retries a delivery", api.post(f"/notifications/outbox/{app_id}/retry", headers=h["auditor"]), 403)
    expect("token in the query string is ignored", api.get("/auth/me", params={"access_token": h["inst.sunrise"]["Authorization"][7:]}), 401)

    # documents: only the owning institution uploads; nobody outside the case's scope lists its documents
    def upload(who, key):
        return api.post(f"/applications/{app_id}/documents", headers={**h[who], "Idempotency-Key": key},
                        data={"doc_type": "LAND_DEED"}, files={"file": ("demo.pdf", TINY_PDF, "application/pdf")})
    expect("other institution uploads to the case", upload("inst.northfield", f"sec-{uuid4().hex[:12]}"), 403)
    expect("auditor uploads to the case", upload("auditor", f"sec-{uuid4().hex[:12]}"), 403)
    expect("regional officer uploads for the institution", upload("ro.southern", f"sec-{uuid4().hex[:12]}"), 403)
    expect("other institution lists the case's documents", api.get(f"/applications/{app_id}/documents", headers=h["inst.northfield"]), 403)
    expect("Southern regional officer lists the case's documents", api.get(f"/applications/{app_id}/documents", headers=h["ro.southern"]), 200)
    expect("regional officer lists another region's documents", api.get("/documents", params={"region": "Northern"}, headers=h["ro.southern"]), 403)
    # compliance: letters are the bureau's; evidence is the institution's; reads stay in scope
    letter = {"application_id": app_id, "institution_id": SUNRISE, "letter_type": "LOA", "academic_year": "2025-26",
              "issue_date": "2025-08-31", "issue_date_source": "PORTAL_EVENT", "f_no": "F.No. DEMO/SEC/0001",
              "lists_deficiencies": False}
    expect("institution registers its own LoA", api.post("/compliance/letters", headers=h["inst.sunrise"], json=letter), 403)
    expect("regional officer registers an LoA", api.post("/compliance/letters", headers=h["ro.southern"], json=letter), 403)
    registered = expect("bureau officer registers the LoA", api.post("/compliance/letters", headers=h["bureau.officer"], json=letter), 201)
    obligation = registered.json()["obligation_ids"][0] if registered.status_code == 201 else str(uuid4())
    expect("other institution reads the case's letters", api.get("/compliance/letters", params={"application_id": app_id}, headers=h["inst.northfield"]), 403)
    expect("other institution reads the obligation", api.get(f"/compliance/obligations/{obligation}", headers=h["inst.northfield"]), 403)
    expect("institution reads its obligation", api.get(f"/compliance/obligations/{obligation}", headers=h["inst.sunrise"]), 200)
    expect("bureau submits evidence for the institution", api.post(f"/compliance/obligations/{obligation}/evidence",
           headers=h["bureau.officer"], json={"document_version_id": str(uuid4())}), 403)
    # alerts: scoped lists; acknowledging is for the addressed role only
    expect("institution lists its alerts", api.get("/alerts", headers=h["inst.sunrise"]), 200)
    expect("auditor lists alerts", api.get("/alerts", headers=h["auditor"]), 200)
    expect("acknowledging an unknown alert", api.post(f"/alerts/{uuid4()}/ack", headers=h["ro.southern"]), 404)
    # API responses carry the strict headers, refusals and sign-in failures included
    for name, response in (("200", api.get("/auth/me", headers=h["auditor"])), ("401", api.get("/applications")),
                           ("403", api.get("/ledger/verify", headers=h["inst.sunrise"]))):
        wrong = [k for k, v in API_HEADERS.items() if response.headers.get(k) != v]
        results.append(not wrong)
        print(f"{'PASS' if not wrong else 'FAIL'}  security headers on a {name} response{': ' + ', '.join(wrong) if wrong else ''}")
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
