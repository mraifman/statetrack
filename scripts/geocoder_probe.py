import json, subprocess, sys
BASE = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
ADDRS = ["1315 10th St, Sacramento, CA 95814", "416 Sid Snyder Ave SW, Olympia, WA 98504", "900 Court St NE, Salem, OR 97301",
         "24 Beacon St, Boston, MA 02133", "1350 Pennsylvania Ave NW, Washington, DC 20004", "400 S Monroe St, Tallahassee, FL 32399"]
for a in ADDRS:
    print("===", a, flush=True)
    r = subprocess.run(["curl", "-sS", "-m", "90", "-G", BASE, "--data-urlencode", f"address={a}", "--data-urlencode", "benchmark=Public_AR_Current",
                        "--data-urlencode", "vintage=Current_Current", "--data-urlencode", "layers=all", "--data-urlencode", "format=json", "-D", "-"],
                       capture_output=True, text=True)
    head, _, body = r.stdout.partition("\r\n\r\n")
    print("\n".join(l for l in head.split("\r\n") if l.lower().startswith(("http", "access-control", "content-type"))))
    try:
        d = json.loads(body)
    except Exception:
        print("not json:", body[:300], r.stderr[:200]); continue
    m = d.get("result", {}).get("addressMatches", [])
    print("matches", len(m))
    if m:
        g = m[0]["geographies"]
        print(list(g))
        for k, v in g.items():
            if "Legislative" in k or "District" in k or "Ward" in k:
                print(" ", k, {x: v[0][x] for x in v[0] if x in ("GEOID", "BASENAME", "NAME", "SLDL", "SLDU", "STATE", "LSAD")})
print("=== JSONP check")
r = subprocess.run(["curl", "-sS", "-m", "90", "-G", BASE, "--data-urlencode", "address=1315 10th St, Sacramento, CA 95814", "--data-urlencode", "benchmark=Public_AR_Current",
                    "--data-urlencode", "vintage=Current_Current", "--data-urlencode", "layers=all", "--data-urlencode", "format=jsonp", "--data-urlencode", "callback=cb"], capture_output=True, text=True)
print(r.stdout[:200])
