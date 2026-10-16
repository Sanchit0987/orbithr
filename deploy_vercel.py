"""Deploy OrbitHR to Vercel via the REST API (no CLI available on this host).

Uploads source files inline and creates a deployment on the user's team.
Token is read from VERCEL_TOKEN env; never hardcode it here.
"""
import json
import os
import sys
import urllib.request

TOKEN = os.environ["VERCEL_TOKEN"]
TEAM = "team_YSZQw1CfCFPeeOb0kQVSJd52"
FILES = ["app.py", "db.py", "ui.py", "views.py", "qr.py", "README.md",
         "vercel.json", "api/index.py"]


def api(path, payload=None, method=None):
    req = urllib.request.Request(
        "https://api.vercel.com" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + TOKEN,
                 "Content-Type": "application/json"},
        method=method or ("POST" if payload is not None else "GET"))
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print("HTTP %s on %s: %s" % (e.code, path, body[:500]))
        sys.exit(1)


here = os.path.dirname(os.path.abspath(__file__))
files = []
for f in FILES:
    with open(os.path.join(here, f), "r", encoding="utf-8") as fh:
        files.append({"file": f, "data": fh.read()})

dep = api("/v13/deployments?teamId=" + TEAM + "&forceNew=1", {
    "name": "orbithr",
    "files": files,
    "target": "production",
    "projectSettings": {"framework": None},
})
print("deployment id:", dep.get("id"))
print("url: https://%s" % dep.get("url"))
print("state:", dep.get("readyState"))

# poll until ready
import time
for _ in range(60):
    time.sleep(5)
    st = api("/v13/deployments/%s?teamId=%s" % (dep["id"], TEAM))
    state = st.get("readyState")
    print("state:", state)
    if state in ("READY", "ERROR", "CANCELED"):
        if state == "READY":
            aliases = st.get("alias") or []
            print("aliases:", aliases)
        break
