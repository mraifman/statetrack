"""Load every state's bills, tags, legislators and history into one normalized structure for the cross-state pages."""
import gzip, json, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATES = json.loads((ROOT / "scripts/states.json").read_text(encoding="utf-8"))
TAX = json.loads((ROOT / "taxonomy/taxonomy.json").read_text(encoding="utf-8"))
SCORE = {"strongly_restricts": -2, "strongly_tightens": -2, "restricts": -1, "tightens": -1, "mixed": 0,
         "expands": 1, "loosens": 1, "strongly_expands": 2, "strongly_loosens": 2}
EXCLUDED = {t["id"] for t in TAX["topics"] if t.get("excluded")}
SUB = {s["id"]: dict(s, topic_id=t["id"], topic=t["name"]) for t in TAX["topics"] for s in t["subtopics"]}
TOPICS = {t["id"]: t for t in TAX["topics"]}
POLICY_TOPICS = [t["id"] for t in TAX["topics"] if not t.get("excluded")]
ACTIVE = {"In Committee Process", "In Floor Process", "Passed", "Pending Referral"}
DEAD = {"Died", "Failed Passage in Committee", "Vetoed"}
OPEN_SESSIONS = {"MA", "DC"}     # sessions still running: nothing there has really "died" yet


def slug(key):
    return re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")


def lean(t):
    return SCORE.get(t["direction"]) if SUB[t["subtopic"]]["axis"] in ("A", "R") else None


def load_state(code):
    d = ROOT / "data" / code.lower()
    bills = json.loads((d / "bills.json").read_text())
    legs = json.loads((d / "legislators.json").read_text())
    ov = d / "legislator_overrides.json"
    if ov.exists():
        for k, fix in json.loads(ov.read_text()).items():
            if k in legs:
                legs[k].update(fix)
    for b in bills.values():
        if code == "DC" and b.get("type") == "PR" and b["status"] == "Chaptered":
            b["status"] = "Adopted"
    tagged = json.loads((d / "tags.json").read_text())["bills"]
    hist = json.load(gzip.open(d / "history.json.gz", "rt"))
    out, authored = {}, defaultdict(int)
    for k, b in bills.items():
        tv = tagged.get(k, {})
        tags = [t for t in tv.get("tags", []) if t["subtopic"] in SUB and SUB[t["subtopic"]]["topic_id"] not in EXCLUDED]
        for t in tags:
            t["lean"] = lean(t)
        parties, lead = set(), ""
        for a in b.get("authors", []):
            lid = a.get("legislator")
            if isinstance(lid, str) and lid in legs:
                authored[lid] += 1
                if legs[lid].get("party"):
                    parties.add(legs[lid]["party"])
                if a.get("role") == "LEAD_AUTHOR" and not lead:
                    lead = legs[lid]["name"]
        h = hist.get(k, [])
        summary = tv.get("summary", "")
        if not tv.get("has_digest", True) or "text was provided" in summary:
            summary = ""
        out[k] = {"key": k, "title": b.get("title", ""), "status": b["status"], "type": b.get("type", ""), "number": b.get("number"),
                  "tags": tags, "topics": sorted({SUB[t["subtopic"]]["topic_id"] for t in tags}), "summary": summary,
                  "intro": h[0][0] if h else "", "last": b.get("last_action_date", ""), "parties": parties, "n_authors": len(b.get("authors", [])),
                  "slug": slug(k), "lead": lead, "url": b.get("url", ""), "ceremonial": any(SUB[t["subtopic"]]["topic_id"] in EXCLUDED for t in tv.get("tags", []) if t["subtopic"] in SUB)}
    return {"code": code, "cfg": STATES[code], "bills": out, "legs": legs, "authored": dict(authored)}


def load_all():
    codes = [c for c in STATES if (ROOT / "data" / c.lower() / "tags.json").exists() and (ROOT / "data" / c.lower() / "bills.json").exists()]
    codes.sort(key=lambda c: (c != "CA", STATES[c]["name"]))
    return {c: load_state(c) for c in codes}
