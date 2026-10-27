"""Demo-day smoke test against a running stack with demo sign-in. Synthetic data only.

    docker compose up -d                        # default stack (DEMO_AUTH=true)
    python scripts/smoke_demo.py --docker       # also queues and delivers a demo alert inside the backend container

Checks what the UI shows: a submitted application in the case list, the deadline and its explanation (deadline
module), the audit timeline and replay, dashboard figures, in-app delivery from a platform fixture, and that the
OCR / obligation / EVC operations really do not exist yet (the UI shows them as previews only).
Real sign-in with Keycloak and Cerbos is covered separately by scripts/smoke_security.py.

Demo clock: time travel lives in the API process. The worker run here is a separate process on real time; that is
fine for freshly queued alerts (due immediately), but retries scheduled in simulated time wait for real time.
"""
import argparse
import subprocess
import sys

import httpx

SUNRISE = "00000000-0000-4000-8000-000000000001"
U = lambda n: f"00000000-0000-4000-9000-{n:012d}"  # noqa: E731
INST = {"X-Demo-User": U(1), "X-Demo-Role": "INSTITUTION", "X-Demo-Institution": SUNRISE}
HEAD = {"X-Demo-User": U(7), "X-Demo-Role": "BUREAU_HEAD"}
SCRUTINY = {"X-Demo-User": U(2), "X-Demo-Role": "SCRUTINY_COMMITTEE"}

results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f': {detail}' if detail else ''}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--docker", action="store_true", help="queue and deliver a demo alert via docker compose exec")
    a = ap.parse_args()
    api = httpx.Client(base_url=f"{a.api}/api", timeout=20)

    config = api.get("/auth/config").json()
    if not check("demo sign-in is on", config["mode"] == "demo", str(config["mode"])):
        print("this script needs DEMO_AUTH=true; use scripts/smoke_security.py for real sign-in")
        return 1

    app = api.post("/applications", headers=INST, json={
        "institution_id": SUNRISE, "category": "NEW_PROGRAMME", "academic_year": "2027-28"}).json()
    submitted = api.post(f"/applications/{app['id']}/submit", headers=INST).json()
    check("application submitted", submitted.get("status") == "IN_PROCESS", submitted.get("current_stage", ""))
    listed = [x["id"] for x in api.get("/applications", headers=INST).json()]
    check("visible in the institution's case list", app["id"] in listed)

    deadlines = api.get(f"/deadlines?subject_id={app['id']}", headers=SCRUTINY).json()
    if check("first deadline opened", len(deadlines) >= 1, ", ".join(d["rule_id"] for d in deadlines)):
        why = api.get(f"/deadlines/{deadlines[0]['id']}/explain", headers=INST).json()
        check("deadline explanation available", bool(why.get("explanation")), f"due {why.get('due_date')}")

    timeline = [e["event_type"] for e in api.get(f"/cases/{app['id']}/timeline", headers=INST).json()]
    check("audit timeline", "wf.application_submitted" in timeline, " -> ".join(timeline))
    replay = api.post("/audit/replay", headers=HEAD).json()
    check("replay ran", replay["verdict"] in ("VERIFIED_COMPLETE", "CONSISTENT_SUBSET"), replay["verdict"])
    dash = {s["key"]: s for s in api.get("/analytics/dashboard", headers=HEAD).json()["sections"]}
    check("dashboard counts applications", dash["applications"]["data"]["total"] >= 1,
          f"total {dash['applications']['data']['total']}, deadlines section {dash['deadlines']['status']}")

    if a.docker:
        run = lambda *cmd: subprocess.run(["docker", "compose", "exec", "-T", "backend", *cmd],  # noqa: E731
                                          capture_output=True, text=True)
        queued = run("python", "-m", "app.platform.demo_seed", "--sample-alerts")
        check("demo alerts queued (platform fixture)", queued.returncode == 0, queued.stdout.strip().splitlines()[-1:])
        delivered = run("python", "-m", "app.platform.notifier", "--once")
        check("worker ran once", delivered.returncode == 0)
        inbox = api.get("/notifications/inbox", headers=INST).json()
        check("in-app notification in the institution's inbox", len(inbox) >= 1, f"{len(inbox)} item(s)")
    else:
        print("SKIP  notification delivery (run with --docker)")

    for path in ("/documents/SAMPLE-LEASE-001/review", "/obligations", "/evc/requests"):
        status = api.get(path, headers=HEAD).status_code
        check(f"{path} is not provided yet (UI preview only)", status == 404, str(status))

    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
