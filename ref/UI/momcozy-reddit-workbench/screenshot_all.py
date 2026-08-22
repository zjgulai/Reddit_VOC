import json, subprocess, time, os

BASE = "http://localhost:5176"
ROUTES = [
    ("analytics", "/dashboard/analytics"),
    ("insights", "/dashboard/insights"),
    ("ugc-showcase", "/dashboard/ugc-showcase"),
    ("settings", "/dashboard/settings"),
]

results = []

for name, path in ROUTES:
    nav = {"action": "navigate", "args": {"url": BASE + path, "newTab": False}}
    ss = {"action": "screenshot", "args": {"format": "png"}}
    open("webbridge_nav.json", "w").write(json.dumps(nav))
    open("webbridge_ss.json", "w").write(json.dumps(ss))

    r1 = subprocess.run(
        ["curl", "-s", "-X", "POST", "http://127.0.0.1:10086/command",
         "-H", "Content-Type: application/json", "-d", "@webbridge_nav.json"],
        capture_output=True, text=True
    )
    time.sleep(3)
    r2 = subprocess.run(
        ["curl", "-s", "-X", "POST", "http://127.0.0.1:10086/command",
         "-H", "Content-Type: application/json", "-d", "@webbridge_ss.json"],
        capture_output=True, text=True
    )
    try:
        path_img = json.loads(r2.stdout).get("data", {}).get("path", "")
    except:
        path_img = ""
    results.append((name, path_img))
    print(f"{name}: {path_img}")

# Also test dashboard weekly tab and sidebar collapsed
for name, path in [("dashboard-weekly", "/dashboard"), ("dashboard-monthly", "/dashboard")]:
    nav = {"action": "navigate", "args": {"url": BASE + path, "newTab": False}}
    open("webbridge_nav.json", "w").write(json.dumps(nav))
    subprocess.run(
        ["curl", "-s", "-X", "POST", "http://127.0.0.1:10086/command",
         "-H", "Content-Type: application/json", "-d", "@webbridge_nav.json"],
        capture_output=True, text=True
    )
    time.sleep(2)

    # Click weekly tab
    if name == "dashboard-weekly":
        click = {"action": "evaluate", "args": {"code": "document.querySelector('button:has-text(\"周报\")')?.click() || document.querySelectorAll('button')[1]?.click()"}}
    else:
        click = {"action": "evaluate", "args": {"code": "document.querySelectorAll('button')[2]?.click()"}}
    open("webbridge_click.json", "w").write(json.dumps(click))
    subprocess.run(
        ["curl", "-s", "-X", "POST", "http://127.0.0.1:10086/command",
         "-H", "Content-Type: application/json", "-d", "@webbridge_click.json"],
        capture_output=True, text=True
    )
    time.sleep(2)
    ss = {"action": "screenshot", "args": {"format": "png"}}
    open("webbridge_ss.json", "w").write(json.dumps(ss))
    r2 = subprocess.run(
        ["curl", "-s", "-X", "POST", "http://127.0.0.1:10086/command",
         "-H", "Content-Type: application/json", "-d", "@webbridge_ss.json"],
        capture_output=True, text=True
    )
    try:
        path_img = json.loads(r2.stdout).get("data", {}).get("path", "")
    except:
        path_img = ""
    results.append((name, path_img))
    print(f"{name}: {path_img}")

for name, path in results:
    print(f"{name} -> {path}")
