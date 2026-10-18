#!/usr/bin/env python3
"""Build the StateTrack California demo as a static site in docs/.

Inputs (data/ca/): bills.json, legislators.json, votes.json.gz, history.json.gz, tags.json, zip_lookup.json;
taxonomy/taxonomy.json (v1.1); scripts/issues.json (the key issues of the moment).

Every number and meter that depends on "hide bills that died" is rendered twice (all bills / bills that did not die)
and a CSS class on <html> chooses which one shows, so the toggle needs no data loading.
Direction is measured against the status quo: current California law as the Legislative Counsel's digest describes it.
"""
import gzip, html, json, re, shutil, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/ca"
OUT = ROOT / "docs"
TAX = json.loads((ROOT / "taxonomy/taxonomy.json").read_text())
SUB = {s["id"]: dict(s, topic_id=t["id"], topic=t["name"]) for t in TAX["topics"] for s in t["subtopics"]}
TOPICS = {t["id"]: t for t in TAX["topics"]}
EXCLUDED = {tid for tid, t in TOPICS.items() if t.get("excluded")}
POLICY_TOPICS = [tid for tid in TOPICS if tid not in EXCLUDED]
ISSUES = json.loads((ROOT / "scripts/issues.json").read_text())
esc = html.escape

SMALL = {"and", "or", "of", "the", "to", "in", "for", "a", "an", "on", "with", "by", "at", "vs.", "vs", "as", "from"}


def T(text):
    """Title Case for category labels (Penalty or Enforcement); acronyms and numbers are kept."""
    out, first = [], True
    for w in re.split(r"(\s+)", str(text).replace("_", " ")):
        if not w.strip():
            out.append(w)
            continue
        m = re.match(r"^([(\"“']*)(.*?)([),.:;\"”']*)$", w)
        pre, core, post = m.group(1), m.group(2), m.group(3)
        if not first and core.lower() in SMALL:
            core = core.lower()
        else:
            core = "-".join(p if (p.isupper() and len(p) > 1) or any(c.isdigit() for c in p) else p[:1].upper() + p[1:] for p in core.split("-"))
        out.append(pre + core + post)
        first = False
    return "".join(out)


for _t in TAX["topics"]:
    _t["name"] = T(_t["name"])
    for _s in _t["subtopics"]:
        _s["name"] = T(_s["name"])
SUB = {s["id"]: dict(s, topic_id=t["id"], topic=t["name"]) for t in TAX["topics"] for s in t["subtopics"]}
TOPICS = {t["id"]: t for t in TAX["topics"]}


def display_note(n):
    n = re.sub(r"\b(restricts|tightens)\s*=\s*", "Restrictive: ", n)
    return re.sub(r"\b(expands|loosens)\s*=\s*", "Permissive: ", n)


DEAD = {"Died", "Failed Passage in Committee", "Vetoed"}
SCORE = {"strongly_restricts": -2, "strongly_tightens": -2, "restricts": -1, "tightens": -1, "mixed": 0,
         "expands": 1, "loosens": 1, "strongly_expands": 2, "strongly_loosens": 2}  # neutral, unclear, not_applicable are left out
ROLE_WEIGHT = {"LEAD_AUTHOR": 3, "PRINCIPAL_COAUTHOR": 2, "COAUTHOR": 1}
MIN_TAGS = 8        # fewer directional tags than this: hollow marker, "rough"
MIN_LEG = 3         # fewer authored directional tags than this: "not enough bills"
CUT = 0.25          # |weighted mean| at or above this earns a Restrictive / Permissive tag


def group(direction):
    return {"strongly_restricts": "rest2", "strongly_tightens": "rest2", "restricts": "rest1", "tightens": "rest1", "mixed": "mixed",
            "neutral": "neutral", "expands": "perm1", "loosens": "perm1", "strongly_expands": "perm2", "strongly_loosens": "perm2"}.get(direction, "other")


GROUP_LABEL = {"rest2": "Strongly Restrictive", "rest1": "Restrictive", "mixed": "Mixed", "neutral": "Neutral",
               "perm1": "Permissive", "perm2": "Strongly Permissive"}
ORDER = ["rest2", "rest1", "mixed", "neutral", "perm1", "perm2"]
DIR_LABEL = {"strongly_restricts": "Strongly Restrictive", "strongly_tightens": "Strongly Restrictive", "restricts": "Restrictive", "tightens": "Restrictive",
             "mixed": "Mixed", "neutral": "Neutral", "expands": "Permissive", "loosens": "Permissive", "strongly_expands": "Strongly Permissive",
             "strongly_loosens": "Strongly Permissive", "unclear": "Unclear", "not_applicable": "—"}
DIR_WORD = lambda d: DIR_LABEL.get(d, T(d))
AXIS = '<div class="axis"><span></span><div class="ends"><span>← Restrictive</span><span>Permissive →</span></div><span></span></div>'
BENCHMARK = ("Every direction is measured against the <b>status quo</b>: current California law, as the Legislative Counsel’s digest describes it. "
             "<b>Permissive</b> means the bill moves the law toward more permission, access or fewer rules. <b>Restrictive</b> means it moves toward less permission or more rules. "
             "A bill that continues, studies or clarifies current law is neutral and is left out of the averages.")

CSS = """
:root{color-scheme:light;--bg:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;--axis:#c3c2b7;--accent:#2a78d6;
--rest2:#a82b2a;--rest1:#e34948;--mixed:#898781;--neutral:#c3c2b7;--perm1:#5598e7;--perm2:#1c5cab;--chip:#efeee9;--link:#1c5cab}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--axis:#383835;--accent:#3987e5;
--rest2:#b84040;--rest1:#e66767;--mixed:#898781;--neutral:#55544f;--perm1:#5598e7;--perm2:#3987e5;--chip:#262624;--link:#6da7ec}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--axis:#383835;--accent:#3987e5;
--rest2:#b84040;--rest1:#e66767;--mixed:#898781;--neutral:#55544f;--perm1:#5598e7;--perm2:#3987e5;--chip:#262624;--link:#6da7ec}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--link)}header.site{background:var(--surface);border-bottom:1px solid var(--line)}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}nav{display:flex;gap:18px;align-items:center;flex-wrap:wrap;padding:12px 0}
nav .brand{font-weight:700;color:var(--ink);text-decoration:none;margin-right:8px}nav a{color:var(--ink2);text-decoration:none}nav a:hover{color:var(--ink);text-decoration:underline}
nav .toggle{margin-left:auto;font-size:14px;color:var(--ink2);display:flex;align-items:center;gap:6px;cursor:pointer}nav .toggle input{width:16px;height:16px}
.v-live{display:none}html.alive .v-live{display:revert}html.alive .v-all{display:none}html.alive .dead{display:none}
main{padding:24px 0 64px}h1{font-size:30px;line-height:1.2;margin:8px 0 6px}h2{font-size:20px;margin:32px 0 8px}h3{font-size:16px;margin:20px 0 6px}
.lede{color:var(--ink2);max-width:70ch;margin:0 0 16px}.muted{color:var(--muted)}.small{font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.tile b{display:block;font-size:28px;line-height:1.1}.tile>span{color:var(--ink2);font-size:13px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
.issues{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin:12px 0}
.issues .card{margin:0;display:flex;flex-direction:column;gap:6px}.issues h3{margin:0;font-size:17px}.issues h3 a{color:var(--ink);text-decoration:none}.issues h3 a:hover{text-decoration:underline}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--ink2);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.bars .row{display:grid;grid-template-columns:minmax(120px,230px) 1fr 56px;gap:10px;align-items:center;padding:3px 0}
.bars .track{height:16px}.bars .fill{height:100%;background:var(--accent);border-radius:0 4px 4px 0;min-width:2px}
.bars a{color:var(--ink);text-decoration:none}.bars a:hover{text-decoration:underline}.bars .v{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin:8px 0;font-size:13px;color:var(--ink2)}.legend span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px;background:var(--c)}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 9px;font-size:12px;color:var(--ink2);margin:1px 4px 1px 0;white-space:nowrap}
.chip.rest{background:var(--rest1);color:#fff}.chip.perm{background:var(--perm1);color:#fff}.chip.mid{background:var(--neutral);color:var(--ink)}
.dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:0}
.party{font-weight:600}.DEM{color:#2a78d6}.REP{color:#d03b3b}
blockquote{margin:6px 0;padding:6px 12px;border-left:3px solid var(--axis);color:var(--ink2);background:var(--surface)}
input[type=text],input:not([type]),select{font:inherit;padding:7px 9px;border:1px solid var(--axis);border-radius:8px;background:var(--surface);color:var(--ink)}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.filters input{flex:1;min-width:200px}
details summary{cursor:pointer;color:var(--ink2)}footer{color:var(--muted);font-size:13px;padding:24px 0;border-top:1px solid var(--line)}
.axis{display:grid;grid-template-columns:minmax(120px,230px) 1fr 92px;gap:10px;font-size:12px;color:var(--ink2);margin-top:8px}.axis .ends{display:flex;justify-content:space-between}
.mrow{display:grid;grid-template-columns:minmax(120px,230px) 1fr 92px;gap:10px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line)}.mrow a{color:var(--ink);text-decoration:none}.mrow a:hover{text-decoration:underline}
.mrow .v{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2);font-size:13px}.mrow.sub{padding-left:14px}
.meter{position:relative;height:18px}.meter::before,.meter::after{content:"";position:absolute;top:7px;height:4px;width:50%}.meter::before{left:0;background:var(--rest1);opacity:.28;border-radius:2px 0 0 2px}.meter::after{right:0;background:var(--perm1);opacity:.28;border-radius:0 2px 2px 0}
.meter .mid{position:absolute;left:50%;top:1px;bottom:1px;width:2px;margin-left:-1px;background:var(--axis);z-index:1}
.meter .avg{position:absolute;top:3px;bottom:3px;width:3px;margin-left:-1.5px;background:var(--ink2);opacity:.7;z-index:1;border-radius:1px}
.meter .dot{position:absolute;top:1px;width:16px;height:16px;margin-left:-8px;border-radius:50%;border:2px solid var(--surface);z-index:2;box-shadow:0 0 0 1px var(--axis)}
.dot.rest{background:var(--rest1)}.dot.perm{background:var(--perm1)}.dot.mid{background:var(--neutral)}.dot.few{background:var(--surface);box-shadow:0 0 0 2px currentColor}.dot.few.rest{color:var(--rest1)}.dot.few.perm{color:var(--perm1)}.dot.few.mid{color:var(--mixed)}
.mini .meter{height:14px}.mini .meter .dot{width:12px;height:12px;margin-left:-6px;top:0}.mini .meter::before,.mini .meter::after{top:5px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}.note{border-left:3px solid var(--accent);padding:6px 12px;background:var(--surface)}
@media (max-width:640px){.bars .row{grid-template-columns:1fr 60px}.bars .track{grid-column:1/-1;order:3}.mrow,.axis{grid-template-columns:1fr 70px}.mrow .meter,.axis .ends{grid-column:1/-1;order:3}nav .toggle{margin-left:0}}
"""

HEAD_JS = """<script>try{if(/[?&]alive=1/.test(location.search)||localStorage.getItem('st_alive')==='1')document.documentElement.classList.add('alive')}catch(e){}</script>"""
TOGGLE_JS = """<script>(function(){var c=document.getElementById('alive');if(!c)return;var r=document.documentElement;c.checked=r.classList.contains('alive');
c.addEventListener('change',function(){r.classList.toggle('alive',c.checked);try{localStorage.setItem('st_alive',c.checked?'1':'0')}catch(e){}window.dispatchEvent(new Event('alivechange'))})})();</script>"""


def slug(key):
    return re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")


def page(title, body, depth=0, desc=""):
    base = "../" * depth
    body = body.replace("<table", '<div class="scroll"><table').replace("</table>", "</table></div>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · StateTrack</title><meta name="description" content="{esc(desc or title)}"><link rel="stylesheet" href="{base}style.css">{HEAD_JS}</head><body>
<header class="site"><div class="wrap"><nav><a class="brand" href="{base}index.html">StateTrack</a><a href="{base}index.html">Overview</a><a href="{base}bills.html">All bills</a>
<a href="{base}find.html">Find my legislators</a><a href="{base}legislators.html">Legislators</a><a href="{base}method.html">How it works</a>
<label class="toggle" title="Hides bills the official record marks as died, failed in committee or vetoed"><input type="checkbox" id="alive"> Hide bills that died</label></nav></div></header>
<main><div class="wrap">{body}</div></main><footer><div class="wrap">Demo for California’s 2025–26 session. Bill data: California Legislative Information (official bulk file). Topics and directions are labelled by an AI model from the bill’s title and the Legislative Counsel’s digest, and are approximate. <a href="{base}method.html">How it works</a></div></footer>{TOGGLE_JS}</body></html>"""


def vv(a, b):
    """Two renderings of the same inline value: all bills / bills that did not die."""
    return f'<span class="v-all">{a}</span><span class="v-live">{b}</span>'


def vb(a, b):
    return f'<div class="v-all">{a}</div><div class="v-live">{b}</div>'


def meter(scores, label="", avg=None):
    """One restrictive-to-permissive line with a marker at the mean score (-2 to +2). Returns (html, mean)."""
    n = len(scores)
    if not n:
        return '<span class="muted small">no directional tags</span>', None
    mean = sum(scores) / n
    pos = (mean + 2) / 4 * 100
    side = "rest" if mean < -CUT / 5 else "perm" if mean > CUT / 5 else "mid"
    restr, perm = sum(1 for x in scores if x < 0), sum(1 for x in scores if x > 0)
    tip = (f"{label}: average {mean:+.2f} against the status quo, from -2 (restrictive) to +2 (permissive), over {n} directional tags "
           f"({restr} restrictive, {perm} permissive, {n - restr - perm} mixed)" + ("; few tags, so treat as rough" if n < MIN_TAGS else ""))
    tick = f'<i class="avg" style="left:{(avg + 2) / 4 * 100:.1f}%" title="all California bills on this topic: {avg:+.2f}"></i>' if avg is not None else ""
    return (f'<div class="meter" role="img" aria-label="{esc(tip)}" title="{esc(tip)}"><i class="mid"></i>{tick}'
            f'<b class="dot {side}{" few" if n < MIN_TAGS else ""}" style="left:{pos:.1f}%"></b></div>'), mean


def main():
    bills = json.loads((DATA / "bills.json").read_text())
    legislators = json.loads((DATA / "legislators.json").read_text())
    votes = json.load(gzip.open(DATA / "votes.json.gz", "rt"))
    history = json.load(gzip.open(DATA / "history.json.gz", "rt"))
    tagged = json.loads((DATA / "tags.json").read_text())["bills"]
    if OUT.exists():
        shutil.rmtree(OUT)
    for d in ("bill", "topic", "legislator", "issue", "data"):
        (OUT / d).mkdir(parents=True)
    (OUT / ".nojekyll").write_text("")
    (OUT / "style.css").write_text(CSS)

    alive = {k: b["status"] not in DEAD for k, b in bills.items()}
    btags = {k: [t for t in v.get("tags", []) if t["subtopic"] in SUB] for k, v in tagged.items()}
    for k in bills:
        btags.setdefault(k, [])
    policy_tags = {k: [t for t in ts if SUB[t["subtopic"]]["topic_id"] not in EXCLUDED] for k, ts in btags.items()}
    ceremonial = {k for k, ts in btags.items() if any(SUB[t["subtopic"]]["topic_id"] in EXCLUDED for t in ts)}
    topic_bills = defaultdict(set)
    sub_bills = defaultdict(set)
    for k, ts in policy_tags.items():
        for t in ts:
            topic_bills[SUB[t["subtopic"]]["topic_id"]].add(k)
            sub_bills[t["subtopic"]].add(k)
    n_policy = sum(1 for k in bills if policy_tags[k])

    def lean(t):
        return SCORE[t["direction"]] if t["direction"] in SCORE and SUB[t["subtopic"]]["axis"] in ("A", "R") else None

    def scores(pred, live):
        out = []
        for k, ts in policy_tags.items():
            if live and not alive[k]:
                continue
            for t in ts:
                s = lean(t)
                if s is not None and pred(k, t):
                    out.append(s)
        return out

    topic_avg = {tid: {lv: (lambda sc: sum(sc) / len(sc) if sc else None)(scores(lambda k, t, tid=tid: SUB[t["subtopic"]]["topic_id"] == tid, lv)) for lv in (False, True)} for tid in POLICY_TOPICS}

    # ---------------- legislators: authorship, votes
    lid_slug = {lid: slug(lid.split(":")[0]) for lid in legislators}
    authored = defaultdict(list)
    for k, b in bills.items():
        for a in b.get("authors", []):
            if isinstance(a["legislator"], str):
                authored[a["legislator"]].append((k, a["role"]))
    cast = defaultdict(dict)
    for k, vs in votes.items():
        for v in vs:
            if "FLOOR" not in v["loc"].upper():
                continue
            for name, m in v["members"].items():
                lid = m.get("legislator")
                if isinstance(lid, str):
                    cur, stamp = cast[lid].get(k), (v["date"], int(v["seq"] or 0))
                    if not cur or stamp >= cur[0]:
                        cast[lid][k] = (stamp, m["vote"])

    # ---------------- bill pages
    def author_line(b):
        out = []
        for a in b.get("authors", []):
            lid = a["legislator"]
            role = T(a["role"])
            if isinstance(lid, str) and lid in legislators:
                out.append(f'<a href="../legislator/{lid_slug[lid]}.html">{esc(legislators[lid]["name"])}</a> <span class="muted small">({role})</span>')
            else:
                out.append(f'{esc(a["name"])} <span class="muted small">({role})</span>')
        return "; ".join(out) or "—"

    def tag_table(k):
        ts = btags[k]
        if not ts:
            if k not in tagged:
                return '<p class="muted">Not tagged yet.</p>'
            if tagged[k].get("refused"):
                return '<p class="muted">Not tagged: the AI model declined to process this bill’s text (its safety filter flagged the subject). Read the digest below.</p>'
            return '<p class="muted">No sub-topic fits this bill, or its digest is too thin to tag.</p>'
        rows = []
        for t in ts:
            s = SUB[t["subtopic"]]
            d = t["direction"]
            g = group(d)
            dot = f'<span class="dot" style="background:var(--{g})"></span>' if g in ORDER else ""
            ev = f'<blockquote>“{esc(t["evidence"])}”</blockquote>' if t.get("evidence") else '<span class="muted small">no quoted support</span>'
            link = f'<a href="../topic/{s["topic_id"]}.html">{esc(s["topic"])}</a> → ' if s["topic_id"] not in EXCLUDED else ""
            rows.append(f'<tr><td>{link}{esc(s["name"])}</td><td>{dot}<b title="{esc(T(d))} (model wording)">{esc(DIR_WORD(d))}</b></td>'
                        f'<td>{esc(T(t["mechanism"]))}</td><td>{esc(T(t["funding"]))}</td><td>{esc(T(t["confidence"]))}</td><td>{ev}</td></tr>')
        return ('<table><thead><tr><th>Topic → sub-topic</th><th>Direction vs. current law</th><th>Mechanism</th><th>Funding</th><th>Confidence</th><th>Quoted from the digest</th></tr></thead><tbody>'
                + "".join(rows) + "</tbody></table>")

    def vote_block(k):
        vs = [v for v in votes.get(k, []) if "FLOOR" in v["loc"].upper()]
        if not vs:
            return '<p class="muted">No recorded floor votes.</p>'
        out = []
        for v in sorted(vs, key=lambda v: (v["date"], int(v["seq"] or 0))):
            by = defaultdict(list)
            for name, m in v["members"].items():
                by[m["vote"]].append(legislators[m["legislator"]]["name"].split(",")[0] if isinstance(m["legislator"], str) and m["legislator"] in legislators else name)
            lists = "".join(f'<p><b>{esc(c)}</b> ({len(n)}): {esc(", ".join(sorted(n)))}</p>' for c, n in sorted(by.items()))
            out.append(f'<details><summary>{esc(v["date"])} · {"Assembly" if v["loc"].upper().startswith("A") else "Senate"} floor · {esc(v["motion"][:90])} · {v["ayes"]}–{v["noes"]}'
                       f'{"–" + str(v["abstain"]) if v["abstain"] else ""} · {esc(v["result"])}</summary>{lists}</details>')
        return "".join(out)

    index = []
    for k, b in sorted(bills.items(), key=lambda kv: (kv[1]["type"], kv[1]["number"])):
        summary = tagged.get(k, {}).get("summary", "")
        if not tagged.get(k, {}).get("has_digest", True) or "text was provided" in summary:
            summary = "Not tagged: the Legislature published no summary for this measure, so its policy effect is not classified."
        hist_rows = "".join(f'<tr><td class="small">{esc(d)}</td><td>{esc(t)}</td></tr>' for d, _, t in history.get(k, [])[-25:][::-1])
        digest = esc(b.get("digest", "")) or '<span class="muted">No digest on file for this bill.</span>'
        body = f"""<p class="small"><a href="../bills.html">← All bills</a></p><h1>{esc(k)} · {esc(b.get("title", ""))}</h1>
<p class="lede">{esc(summary)}</p>
<div class="tiles"><div class="tile"><b style="font-size:18px">{esc(b["status"])}</b><span>Status</span></div><div class="tile"><b style="font-size:18px">{esc(b.get("last_action_date", ""))}</b><span>Last action</span></div>
<div class="tile"><b style="font-size:18px">{esc(b["house"])}</b><span>Currently in</span></div></div>
<p><b>Authors:</b> {author_line(b)}</p>
<h2>Topic tags</h2><p class="small muted">Direction is measured against current California law as described in the digest.</p>{tag_table(k)}
<h2>What the bill does (Legislative Counsel’s digest)</h2><div class="card small">{digest}</div>
<h2>Floor votes</h2>{vote_block(k)}
<h2>Recent actions</h2><table><tbody>{hist_rows}</tbody></table>
<p class="small"><a href="https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id={esc(b["id"])}">Official record on leginfo.legislature.ca.gov ↗</a></p>"""
        (OUT / "bill" / f"{slug(k)}.html").write_text(page(k, body, 1, summary or b.get("title", "")))
        index.append({"k": k, "s": slug(k), "t": b.get("title", ""), "st": b["status"],
                      "tp": sorted({SUB[t["subtopic"]]["topic_id"] for t in policy_tags[k]}),
                      "d": sorted({group(t["direction"]) for t in policy_tags[k] if group(t["direction"]) in ORDER}), "su": summary})

    def bill_li(k, extra="", depth=1):
        b = bills[k]
        return f'<li class="{"" if alive[k] else "dead"}"><a href="{"../" * depth}bill/{slug(k)}.html">{esc(k)}</a> · {esc(b.get("title", ""))} <span class="chip">{esc(b["status"])}</span>{extra}</li>'

    # ---------------- topic pages
    def sub_scores(sid, live):
        return scores(lambda k, t: t["subtopic"] == sid, live)

    for tid in POLICY_TOPICS:
        t = TOPICS[tid]

        def block(live):
            rows = []
            for ax, label in (("A", "Access and rights"), ("R", "Regulation")):
                sc = scores(lambda k, tg, ax=ax: SUB[tg["subtopic"]]["topic_id"] == tid and SUB[tg["subtopic"]]["axis"] == ax, live)
                if sc:
                    m, mean = meter(sc, f"{t['name']}: {label.lower()}", topic_avg[tid][live])
                    rows.append(f'<div class="mrow"><span><b>{label}</b></span>{m}<div class="v">{mean:+.2f} <span class="muted small">n={len(sc)}</span></div></div>')
            head = (f'<h2>Where this topic leans</h2><p class="small muted">Two questions are kept apart: how the bills treat <b>access and rights</b>, and how they treat <b>regulation</b>. '
                    f'The grey tick is the average of all directional tags on this topic.</p>{AXIS}{"".join(rows)}') if rows else ""
            subs = []
            for s in t["subtopics"]:
                n = len({k for k in sub_bills.get(s["id"], ()) if not live or alive[k]})
                if s["axis"] in ("A", "R"):
                    m, mean = meter(sub_scores(s["id"], live), s["name"])
                    lean_txt = f"{mean:+.2f}" if mean is not None else ""
                else:
                    m, lean_txt = f'<span class="muted small">{"funding only" if s["axis"] == "F" else "no direction"}</span>', ""
                note = f'<div class="muted small">{esc(display_note(s["note"]))}</div>' if s.get("note") else ""
                subs.append(f'<div class="mrow sub"><span><a href="#{slug(s["id"])}">{esc(s["name"])}</a> <span class="muted small">({n})</span>{note}</span>{m}<div class="v">{lean_txt}</div></div>')
            return head + f'<h2>Sub-topics</h2>{AXIS}{"".join(subs)}'

        lists = []
        for s in t["subtopics"]:
            ks = sorted(sub_bills.get(s["id"], ()), key=lambda k: (bills[k]["type"], bills[k]["number"]))
            if not ks:
                continue
            td = {k: next((x["direction"] for x in btags[k] if x["subtopic"] == s["id"]), "") for k in ks}
            lis = "".join(bill_li(k, f' <span class="chip">{esc(DIR_WORD(td[k]))}</span>' if td[k] and td[k] != "not_applicable" else "") for k in ks[:300])
            more = f'<p class="muted small">Showing the first 300 of {len(ks)}; use <a href="../bills.html">All bills</a> to search.</p>' if len(ks) > 300 else ""
            lists.append(f'<h3 id="{slug(s["id"])}">{esc(s["name"])} <span class="muted small">({vv(len(ks), len([k for k in ks if alive[k]]))})</span></h3><ul>{lis}</ul>{more}')
        n_all, n_live = len(topic_bills[tid]), len([k for k in topic_bills[tid] if alive[k]])
        body = (f'<p class="small"><a href="../index.html">← Overview</a></p><h1>{esc(t["name"])}</h1>'
                f'<p class="lede">{vv(n_all, n_live)} California bills carry at least one tag under this topic. A bill can appear under several sub-topics.</p>'
                f'<div class="note small">{BENCHMARK}</div>{vb(block(False), block(True))}'
                f'<p class="small muted">Each marker is the average of its bills’ directions, from restrictive (−2) to permissive (+2). Neutral and unclear tags are left out; mixed counts as 0. A hollow marker means fewer than {MIN_TAGS} directional tags, so treat it as rough.</p>'
                + "".join(lists))
        (OUT / "topic" / f"{tid}.html").write_text(page(t["name"], body, 1))

    # ---------------- key issues
    def issue_match(iss, k):
        sub_hit = any(t["subtopic"] in iss["subtopics"] for t in btags[k]) if iss["subtopics"] else False
        topic_hit = any(SUB[t["subtopic"]]["topic_id"] == iss.get("topic") for t in btags[k]) if iss.get("topic") else False
        rx = re.compile(iss["regex"], re.I) if iss.get("regex") else None
        text_hit = False
        if rx:
            b = bills[k]
            text_hit = bool(rx.search(b.get("title", ""))) or len(rx.findall(b.get("digest", ""))) >= iss.get("min_mentions", 2)
        return sub_hit or topic_hit or text_hit

    issue_cards, issue_data = [], []
    for iss in ISSUES["issues"]:
        ks = sorted((k for k in bills if issue_match(iss, k)), key=lambda k: (bills[k]["type"], bills[k]["number"]))
        if len(ks) < ISSUES.get("min_bills", 8):
            continue
        issue_data.append((iss, ks))
    issue_data = issue_data[:ISSUES.get("max_issues", 10)]

    def status_counts(ks, live):
        c = Counter(bills[k]["status"] for k in ks if not live or alive[k])
        return c

    def issue_scores(iss, ks, live):
        subs = set(iss["subtopics"]) or None
        if iss.get("topic"):
            subs = {s["id"] for s in TOPICS[iss["topic"]]["subtopics"]}
        if not subs:
            return []
        out = []
        for k in ks:
            if live and not alive[k]:
                continue
            for t in btags[k]:
                s = lean(t)
                if s is not None and t["subtopic"] in subs:
                    out.append(s)
        return out

    for iss, ks in issue_data:
        def card_stats(live, ks=ks, iss=iss):
            kk = [k for k in ks if not live or alive[k]]
            c = Counter(bills[k]["status"] for k in kk)
            m, mean = meter(issue_scores(iss, ks, live), iss["name"])
            return (f'<div class="small">{len(kk)} bills · {c.get("Chaptered", 0)} signed into law · {c.get("Vetoed", 0)} vetoed'
                    f'{"" if live else " · " + str(sum(c.get(s, 0) for s in DEAD)) + " died"}</div><div class="mini">{m}</div>')
        issue_cards.append(f'<div class="card"><h3><a href="issue/{iss["id"]}.html">{esc(iss["name"])}</a></h3><div class="small muted">{esc(iss["hook"])}</div>{vb(card_stats(False), card_stats(True))}</div>')

        def issue_block(live, iss=iss, ks=ks):
            kk = [k for k in ks if not live or alive[k]]
            c = Counter(bills[k]["status"] for k in kk)
            active = sum(c.get(s, 0) for s in ("In Committee Process", "In Floor Process", "Passed", "Pending Referral"))
            tiles = (f'<div class="tiles"><div class="tile"><b>{len(kk)}</b><span>bills</span></div><div class="tile"><b>{c.get("Chaptered", 0)}</b><span>signed into law</span></div>'
                     f'<div class="tile"><b>{c.get("Vetoed", 0)}</b><span>vetoed</span></div>'
                     f'{"" if live else "<div class=tile><b>" + str(sum(c.get(s, 0) for s in DEAD)) + "</b><span>died</span></div>"}'
                     f'<div class="tile"><b>{active}</b><span>still listed as active</span></div></div>')
            sc = issue_scores(iss, ks, live)
            lean_html = ""
            if sc:
                m, mean = meter(sc, iss["name"])
                lean_html = f'<h2>Where the bills lean</h2>{AXIS}<div class="mrow"><span><b>{esc(iss["name"])}</b></span>{m}<div class="v">{mean:+.2f} <span class="muted small">n={len(sc)}</span></div></div>'
            leads = Counter()
            for k in kk:
                for a in bills[k].get("authors", []):
                    if isinstance(a["legislator"], str) and a["role"] in ("LEAD_AUTHOR", "PRINCIPAL_COAUTHOR"):
                        leads[a["legislator"]] += 1
            lead_html = ""
            if leads:
                lead_html = ('<h2>Most active authors</h2><p class="small muted">Lead authors and principal co-authors of the bills on this issue.</p><ul>' +
                             "".join(f'<li><a href="../legislator/{lid_slug[lid]}.html">{esc(legislators[lid]["name"])}</a> <span class="party {legislators[lid]["party"]}">{esc(legislators[lid]["party"])}</span> · {n} bill{"" if n == 1 else "s"}</li>'
                                     for lid, n in leads.most_common(8)) + "</ul>")
            return tiles + lean_html + lead_html

        src = "".join(f'<li><a href="{esc(u)}">{esc(l)}</a></li>' for l, u in iss["sources"])
        scope = []
        if iss["subtopics"]:
            scope.append("tagged under " + ", ".join(esc(SUB[s]["name"]) for s in iss["subtopics"] if s in SUB))
        if iss.get("topic"):
            scope.append(f"every sub-topic of {esc(TOPICS[iss['topic']]['name'])}")
        if iss.get("regex"):
            scope.append("whose title or digest mentions " + " or ".join(f"“{esc(x)}”" for x in iss["terms"]) + f" (in the title, or at least {iss.get('min_mentions', 2)} times in the digest)")
        order = {"Chaptered": 0, "Vetoed": 1, "Passed": 2, "In Floor Process": 3, "In Committee Process": 4, "Pending Referral": 5}
        lis = "".join(bill_li(k) for k in sorted(ks, key=lambda k: (order.get(bills[k]["status"], 6), bills[k]["type"], bills[k]["number"]))[:400])
        body = (f'<p class="small"><a href="../index.html">← Overview</a></p><h1>{esc(iss["name"])}</h1><p class="lede">{esc(iss["hook"])}</p>'
                f'<p class="small muted">In the news ({esc(ISSUES["as_of"])}). Press coverage as found by search; open the sources for the full story:</p><ul class="small">{src}</ul>'
                f'<p class="small muted">Bills on this page: {"; ".join(scope)}.</p><div class="note small">{BENCHMARK}</div>{vb(issue_block(False), issue_block(True))}'
                f'<h2>Bills</h2><ul>{lis}</ul>')
        (OUT / "issue" / f"{iss['id']}.html").write_text(page(iss["name"], body, 1, iss["hook"]))

    # ---------------- legislator pages
    leg_rows = []
    for lid, L in sorted(legislators.items(), key=lambda kv: kv[1]["name"]):
        if not L["active"]:
            continue
        au = authored.get(lid, [])
        vt = cast.get(lid, {})

        def leg_block(live, lid=lid, au=au, vt=vt):
            a_k = [(k, r) for k, r in au if not live or alive[k]]
            v_k = {k: v for k, v in vt.items() if not live or alive[k]}
            aye = sum(1 for _, v in v_k.values() if v == "AYE")
            noe = sum(1 for _, v in v_k.values() if v == "NOE")
            tiles = (f'<div class="tiles"><div class="tile"><b>{len(a_k)}</b><span>bills authored or co-authored</span></div><div class="tile"><b>{len(v_k)}</b><span>bills with a recorded floor vote</span></div>'
                     f'<div class="tile"><b>{aye}</b><span>aye votes</span></div><div class="tile"><b>{noe}</b><span>no votes</span></div></div>')
            # lean by issue (weighted authorship)
            per = defaultdict(list)
            for k, role in a_k:
                w = ROLE_WEIGHT.get(role, 1)
                for t in policy_tags[k]:
                    s = lean(t)
                    if s is not None:
                        per[SUB[t["subtopic"]]["topic_id"]].append((s, w))
            rows = []
            for tid, items in sorted(per.items(), key=lambda kv: -len(kv[1])):
                n = len(items)
                wm = sum(s * w for s, w in items) / sum(w for _, w in items)
                if n < MIN_LEG:
                    chip, m = '<span class="chip">Not enough bills</span>', '<span class="muted small">fewer than 3 directional bills</span>'
                else:
                    m, _ = meter([wm], TOPICS[tid]["name"], topic_avg[tid][live])
                    m = m.replace('<b class="dot', '<b class="dot') if n >= MIN_TAGS else m
                    kind, word = ("rest", "Restrictive") if wm <= -CUT else ("perm", "Permissive") if wm >= CUT else ("mid", "Balanced")
                    chip = f'<span class="chip {kind}">{word}</span>'
                rows.append(f'<div class="mrow"><a href="../topic/{tid}.html">{esc(TOPICS[tid]["name"])}</a>{m}<div class="v">{chip}<br><span class="muted small">{n} bill{"" if n == 1 else "s"}</span></div></div>')
            lean_html = (f'<h2>Lean by issue</h2><p class="small muted">From the bills this legislator authored or co-authored. Each bill’s direction is measured against current law; lead authors count 3×, principal co-authors 2×, co-authors 1×. '
                         f'A tag needs at least {MIN_LEG} directional bills; <b>Restrictive</b> is a weighted average of −{CUT} or lower, <b>Permissive</b> is +{CUT} or higher, otherwise <b>Balanced</b>. '
                         f'The dark tick is the average of all California bills on the topic, so you can see where this legislator sits relative to the typical bill.</p>{AXIS}{"".join(rows) if rows else "<p class=muted>No tagged bills with a direction.</p>"}')
            # detail by sub-topic
            prof = defaultdict(lambda: defaultdict(int))
            for k, role in a_k:
                for t in policy_tags[k]:
                    if SUB[t["subtopic"]]["axis"] in ("A", "R"):
                        g = group(t["direction"])
                        pole = "R" if g in ("rest1", "rest2") else "P" if g in ("perm1", "perm2") else "N" if g in ("neutral", "mixed") else None
                        if pole:
                            prof[t["subtopic"]][f"au{pole}"] += 1
            for k, (_, v) in v_k.items():
                for t in policy_tags[k]:
                    if SUB[t["subtopic"]]["axis"] in ("A", "R") and v in ("AYE", "NOE"):
                        g = group(t["direction"])
                        pole = "R" if g in ("rest1", "rest2") else "P" if g in ("perm1", "perm2") else None
                        if pole:
                            prof[t["subtopic"]][("ay" if v == "AYE" else "no") + pole] += 1
            drows = "".join(f'<tr><td>{esc(SUB[sid]["topic"])} → {esc(SUB[sid]["name"])}</td><td class="n">{c["auR"]}</td><td class="n">{c["auP"]}</td><td class="n">{c["auN"]}</td>'
                            f'<td class="n">{c["ayR"]}</td><td class="n">{c["ayP"]}</td><td class="n">{c["noR"]}</td><td class="n">{c["noP"]}</td></tr>'
                            for sid, c in sorted(prof.items(), key=lambda kv: -sum(kv[1].values())))
            detail = ('<h2>Record by sub-topic</h2><table><thead><tr><th rowspan="2">Sub-topic</th><th colspan="3" class="n">Authored or Co-authored</th><th colspan="2" class="n">Voted Aye on</th><th colspan="2" class="n">Voted No on</th></tr>'
                      '<tr><th class="n">Restrictive</th><th class="n">Permissive</th><th class="n">Neutral or Mixed</th><th class="n">Restrictive</th><th class="n">Permissive</th><th class="n">Restrictive</th><th class="n">Permissive</th></tr></thead><tbody>'
                      + drows + "</tbody></table>") if drows else ""
            return tiles + lean_html + detail

        au_sorted = sorted(au, key=lambda x: (x[1] != "LEAD_AUTHOR", bills[x[0]]["type"], bills[x[0]]["number"]))
        au_list = "".join(bill_li(k, f' <span class="chip">{esc(T(role))}</span>') for k, role in au_sorted[:400])
        body = f"""<p class="small"><a href="../legislators.html">← All legislators</a></p><h1>{esc(L["name"])}</h1>
<p class="lede"><span class="party {L["party"]}">{esc({"DEM": "Democrat", "REP": "Republican"}.get(L["party"], L["party"]))}</span> · {esc(L["house"])} · District {esc(re.sub(r"^[A-Z]+0*", "", lid.split(":")[0]))}</p>
{vb(leg_block(False), leg_block(True))}
<p class="note small">These come from what this legislator authored and how they voted on tagged bills, with the bills linked below. A co-author may sign on to a bill they have reservations about, and a vote reflects one amendment stage. Most bills that reach a floor vote pass with large majorities and almost every member votes aye, so aye counts mostly mirror what reached the floor; authorship is the more distinctive signal. Treat the tags as a summary of the record, not a rating. Only floor votes are counted; committee votes are not matched to members yet.</p>
<h2>Bills authored ({len(au)})</h2><ul>{au_list}</ul>"""
        (OUT / "legislator" / f"{lid_slug[lid]}.html").write_text(page(L["name"], body, 1))
        leg_rows.append((L, lid, len(au), len([k for k, _ in au if alive[k]]), len(vt)))
    rows = "".join(f'<tr><td><a href="legislator/{lid_slug[lid]}.html">{esc(L["name"])}</a></td><td><span class="party {L["party"]}">{esc(L["party"])}</span></td><td>{esc(L["house"])}</td>'
                   f'<td>{esc(re.sub(r"^[A-Z]+0*", "", lid.split(":")[0]))}</td><td class="n">{vv(na, nal)}</td><td class="n">{nv}</td></tr>' for L, lid, na, nal, nv in leg_rows)
    (OUT / "legislators.html").write_text(page("Legislators", f'<h1>Legislators</h1><p class="lede">{len(leg_rows)} members of the 2025–26 California Legislature.</p>'
        f'<table><thead><tr><th>Name</th><th>Party</th><th>House</th><th>District</th><th class="n">Bills authored</th><th class="n">Bills voted on (floor)</th></tr></thead><tbody>{rows}</tbody></table>'))

    # ---------------- find my legislators
    zips = json.loads((DATA / "zip_lookup.json").read_text())
    (OUT / "data" / "zip-ca.json").write_text(json.dumps(zips, separators=(",", ":")))
    reps = {"A": {}, "S": {}}
    for L, lid, na, nal, nv in leg_rows:
        code = lid.split(":")[0]
        ch = "A" if code.startswith("AD") else "S" if code.startswith("SD") else None
        if ch and code[2:].isdigit():
            reps[ch][int(code[2:])] = {"n": L["name"], "s": lid_slug[lid], "p": L["party"], "a": na}
    find_js = """const REPS=__REPS__;let Z=null;
const box=document.getElementById('zip'),out=document.getElementById('res');
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
const PARTY={DEM:'Democrat',REP:'Republican'};
function card(ch,d,share,only){const r=REPS[ch][d];const name=ch==='A'?'Assembly District ':'State Senate District ';
if(!r)return '<li>'+name+d+' (no current member on file)</li>';
const pct=Math.round(share*100);
return '<li class="card"><b><a href="legislator/'+r.s+'.html">'+esc(r.n.split(', ').reverse().join(' '))+'</a></b> <span class="party '+r.p+'">'+esc(PARTY[r.p]||r.p)+'</span><br><span class="muted small">'+name+d+
(only?' · covers the whole ZIP code':' · covers about '+pct+'% of this ZIP code')+' · '+r.a+' bills authored or co-authored</span></li>'}
function section(ch,label,list){if(!list||!list.length)return '';const sure=list.length===1;
return '<h2>'+label+'</h2>'+(sure?'':'<p class="muted small">This ZIP code is split between districts. Percentages are the share of the ZIP code’s land area in each district, so they show which is likelier, not who lives where.</p>')+'<ul style="list-style:none;padding:0">'+list.map(x=>card(ch,x[0],x[1],sure)).join('')+'</ul>'}
async function go(){const raw=box.value.trim();const m=raw.match(/^(\\d{5})(?:-\\d{4})?$/);
if(!m){out.innerHTML='<p class="note">Enter a 5-digit ZIP code, for example 94110.</p>';return}
const zip=m[1];history.replaceState(null,'','?zip='+zip);
if(!Z){try{Z=await (await fetch('data/zip-ca.json')).json()}catch(e){out.innerHTML='<p class="note">The ZIP lookup could not be loaded. Please try again.</p>';return}}
const r=Z[zip];
if(!r){out.innerHTML='<p class="note">No California legislators found for '+zip+'. This demo covers California only, and some ZIP codes (such as PO boxes) are not matched to districts. Try your street address on the <a href="https://findyourrep.legislature.ca.gov/">official lookup</a>.</p>';return}
out.innerHTML='<h2 style="margin-top:20px">ZIP code '+zip+'</h2>'+section('A','Assembly member',r.A)+section('S','State senator',r.S)+
'<p class="note small">ZIP codes and legislative districts do not line up exactly. For a definite answer, enter your street address on the <a href="https://findyourrep.legislature.ca.gov/">California Legislature’s official lookup</a>.</p>'}
document.getElementById('f').addEventListener('submit',e=>{e.preventDefault();go()});
const q=new URLSearchParams(location.search).get('zip');if(q){box.value=q;go()}""".replace("__REPS__", json.dumps(reps, separators=(",", ":"), ensure_ascii=False))
    (OUT / "find.html").write_text(page("Find my legislators", f"""<h1>Find my legislators</h1>
<p class="lede">Enter a California ZIP code to see your state Assembly member and state senator, then what each of them has authored and how they have voted.</p>
<form id="f" class="filters" autocomplete="off"><input id="zip" inputmode="numeric" maxlength="10" placeholder="ZIP code, for example 94110" aria-label="ZIP code" style="max-width:260px"><button type="submit" style="font:inherit;padding:7px 16px;border-radius:8px;border:1px solid var(--axis);background:var(--accent);color:#fff;cursor:pointer">Find</button></form>
<p class="muted small">Try <a href="?zip=94110">94110</a> (one district), <a href="?zip=90210">90210</a> (split across districts) or <a href="?zip=95814">95814</a>.</p>
<div id="res"></div><script>{find_js}</script>"""))

    # ---------------- overview
    def topic_meters(live):
        rows = []
        for tid in POLICY_TOPICS:
            sc = scores(lambda k, t, tid=tid: SUB[t["subtopic"]]["topic_id"] == tid, live)
            if sc:
                m, mean = meter(sc, TOPICS[tid]["name"])
                rows.append((mean, tid, sc, m))
        rows.sort()
        skipped = [TOPICS[tid]["name"] for tid in POLICY_TOPICS if not any(r[1] == tid for r in rows)]
        out = "".join(f'<div class="mrow"><a href="topic/{tid}.html">{esc(TOPICS[tid]["name"])}</a>{m}<div class="v">{mean:+.2f} <span class="muted small">n={len(sc)}</span></div></div>' for mean, tid, sc, m in rows)
        if skipped:
            out += f'<p class="small muted">Not on the meter: {esc(", ".join(skipped))} (no directional tags).</p>'
        return AXIS + out

    def topic_bars(live):
        counts = sorted(((len([k for k in topic_bills[tid] if not live or alive[k]]), tid) for tid in POLICY_TOPICS), reverse=True)
        top = counts[0][0] or 1
        return '<div class="bars">' + "".join(f'<div class="row"><a href="topic/{tid}.html">{esc(TOPICS[tid]["name"])}</a><div class="track" title="{esc(TOPICS[tid]["name"])}: {n} bills"><div class="fill" style="width:{100 * n / top:.1f}%"></div></div><div class="v">{n}</div></div>' for n, tid in counts) + "</div>"

    status = Counter(b["status"] for b in bills.values())
    n_dead = sum(status[s] for s in DEAD)
    issues_html = (f'<h2>Issues in the news</h2><p class="small muted">Chosen from California coverage as of {esc(ISSUES["as_of"])}. Each links to the bills, how they lean and who is authoring them.</p><div class="issues">{"".join(issue_cards)}</div>') if issue_cards else ""
    body = f"""<h1>California legislation by topic and direction</h1>
<p class="lede">Every bill in California’s 2025–26 session, sorted into topics, with a read on which way each bill pushes against current law, Restrictive or Permissive, and where the money goes. Then what each legislator authored and how they voted.</p>
<div class="tiles"><div class="tile"><b>{vv(f"{len(bills):,}", f"{len(bills) - n_dead:,}")}</b><span>bills</span></div><div class="tile"><b>{vv(f"{n_policy:,}", f"{sum(1 for k in bills if policy_tags[k] and alive[k]):,}")}</b><span>with policy topic tags</span></div><div class="tile"><b>{len(leg_rows)}</b><span>legislators</span></div>
<div class="tile"><b>{status.get("Chaptered", 0):,}</b><span>signed into law (chaptered)</span></div></div>
<form class="filters" action="find.html" method="get"><input name="zip" inputmode="numeric" maxlength="10" placeholder="Find my legislators: enter a California ZIP code" aria-label="ZIP code"><button type="submit" style="font:inherit;padding:7px 16px;border-radius:8px;border:1px solid var(--axis);background:var(--accent);color:#fff;cursor:pointer">Find</button></form>
{issues_html}
<h2>How to read the meter</h2><div class="note small">{BENCHMARK} The <b>Hide bills that died</b> switch in the header drops the {n_dead} bills the official record marks as died, failed in committee or vetoed. Bills still listed as in committee cannot pass once the session has ended, but they are only hidden if the record says they died.</div>
<h2>Where each topic leans</h2><p class="small muted">Each marker is the average direction of the bills tagged under that topic, from restrictive to permissive. Neutral and unclear tags are left out. A marker near the middle can hide a split: open the topic to see access and regulation separately.</p>{vb(topic_meters(False), topic_meters(True))}
<h2>Bills by topic</h2><p class="small muted">A bill counts once under each topic it touches, so bars add up to more than the number of bills. {len(ceremonial)} ceremonial or commemorative measures (naming, honoring) are not counted here.</p>{vb(topic_bars(False), topic_bars(True))}
<h2>Where to start</h2><ul><li><a href="bills.html">Search all bills</a> by words, topic, status or direction.</li><li><a href="find.html">Find my legislators</a> by ZIP code.</li><li><a href="legislators.html">Legislators</a>: a Restrictive / Permissive tag for each issue, plus authorship and floor votes.</li><li><a href="method.html">How it works</a>, and what the labels can and cannot tell you.</li></ul>"""
    (OUT / "index.html").write_text(page("California by topic", body))

    # ---------------- bills search
    opts_t = "".join(f'<option value="{tid}">{esc(TOPICS[tid]["name"])}</option>' for tid in POLICY_TOPICS)
    opts_s = "".join(f"<option>{esc(s)}</option>" for s in sorted(status))
    opts_d = "".join(f'<option value="{g}">{GROUP_LABEL[g]}</option>' for g in ORDER)
    js = """const D=__D__;const TN=__TN__;const DEAD=__DEAD__;
const q=document.getElementById('q'),tp=document.getElementById('tp'),st=document.getElementById('st'),dr=document.getElementById('dr'),out=document.getElementById('out'),cnt=document.getElementById('cnt');
function esc(s){return s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function run(){const hide=document.documentElement.classList.contains('alive');const w=q.value.toLowerCase().trim().split(/\\s+/).filter(Boolean);let n=0,h='';
for(const b of D){if(hide&&DEAD.includes(b.st))continue;if(tp.value&&!b.tp.includes(tp.value))continue;if(st.value&&b.st!==st.value)continue;if(dr.value&&!b.d.includes(dr.value))continue;
const hay=(b.k+' '+b.t+' '+b.su).toLowerCase();if(w.some(x=>!hay.includes(x)))continue;n++;
if(n<=200)h+='<tr><td><a href="bill/'+b.s+'.html">'+esc(b.k)+'</a></td><td>'+esc(b.t)+'<div class="muted small">'+esc(b.su)+'</div></td><td>'+esc(b.st)+'</td><td>'+b.tp.map(t=>'<span class="chip">'+esc(TN[t])+'</span>').join('')+'</td></tr>'}
out.innerHTML=h;cnt.textContent=n+' bills'+(n>200?' (showing the first 200; narrow the search)':'')}
[q,tp,st,dr].forEach(e=>e.addEventListener('input',run));window.addEventListener('alivechange',run);run();""".replace("__D__", json.dumps(index, separators=(",", ":"), ensure_ascii=False)).replace("__TN__", json.dumps({tid: TOPICS[tid]["name"] for tid in POLICY_TOPICS})).replace("__DEAD__", json.dumps(sorted(DEAD)))
    (OUT / "bills.html").write_text(page("All bills", f"""<h1>All bills</h1><p class="lede">Search {len(bills):,} California bills.</p>
<div class="filters"><input id="q" placeholder="Search bill number, title or summary" aria-label="Search"><select id="tp" aria-label="Topic"><option value="">Any topic</option>{opts_t}</select>
<select id="st" aria-label="Status"><option value="">Any status</option>{opts_s}</select><select id="dr" aria-label="Direction"><option value="">Any direction</option>{opts_d}</select></div>
<p class="muted small" id="cnt"></p><table><thead><tr><th>Bill</th><th>Title</th><th>Status</th><th>Topics</th></tr></thead><tbody id="out"></tbody></table><script>{js}</script>"""))

    # ---------------- method
    taxrows = "".join(f'<li><b>{esc(t["name"])}</b>: ' + ", ".join(esc(s["name"]) for s in t["subtopics"]) + "</li>" for t in TAX["topics"] if not t.get("excluded"))
    meta = json.loads((DATA / "tags.json").read_text())
    (OUT / "method.html").write_text(page("How it works", f"""<h1>How it works</h1>
<h2>The benchmark: current law</h2><p>{BENCHMARK}</p>
<h2>What is labelled</h2><p>Each California bill gets one or more tags. A tag has a <b>sub-topic</b> from a fixed two-level list ({len(POLICY_TOPICS)} topics, {sum(len(TOPICS[t]["subtopics"]) for t in POLICY_TOPICS)} sub-topics, version {esc(TAX["version"])}), a <b>direction</b> against the status quo, a <b>mechanism</b> (a ban, a licensing rule, a tax incentive, a study) and a <b>funding</b> note (increases, decreases, none). Ceremonial measures (naming, honoring) are tagged as “not a policy topic” and left out of the charts.</p>
<h2>Direction</h2><p>Every bill is labelled Restrictive, Permissive, Mixed or Neutral on each sub-topic it touches, with “Strongly” where the change is large. The AI model’s own wording differs by sub-topic (expands or restricts for access and rights, tightens or loosens for regulation); the site maps both to Permissive and Restrictive, and the original word appears as a tooltip. Funding-only sub-topics have no direction. Studies, assessments, voluntary programs and rules that only assign responsibility are Neutral. Direction describes what a bill does, not whether that is good or bad.</p>
<h2>The restrictive-to-permissive meter</h2><p>Each directional tag is scored: Strongly Restrictive −2, Restrictive −1, Mixed 0, Permissive +1, Strongly Permissive +2. A marker sits at the average. Neutral, unclear and funding-only tags are left out, and a hollow marker means fewer than {MIN_TAGS} directional tags. The average hides disagreement inside a topic, so topic pages show access and regulation separately.</p>
<h2>Hide bills that died</h2><p>The switch in the header removes bills whose official status is “Died”, “Failed Passage in Committee” or “Vetoed” from every count, meter and list. A bill still shown as “in committee” after the session ended cannot pass, but it is not hidden unless the record marks it as died.</p>
<h2>Legislator tags</h2><p>On each legislator’s page, every issue gets a <b>Restrictive</b>, <b>Permissive</b> or <b>Balanced</b> tag from the bills they authored or co-authored. Lead authors count 3×, principal co-authors 2× and co-authors 1×. A tag needs at least {MIN_LEG} directional bills; a weighted average of −{CUT} or lower is Restrictive and +{CUT} or higher is Permissive. The tag describes the bills, not the person’s views, and co-authors sometimes sign on without strong support. The dark tick on each meter marks the average of all California bills on that topic.</p>
<h2>Issues in the news</h2><p>The issues on the overview were picked from news coverage as of {esc(ISSUES["as_of"])}. Each issue page lists its sources and states exactly which bills it includes (by tag and by wording in the title or digest). Keyword matching can include a bill that only mentions the subject in passing.</p>
<h2>Evidence</h2><p>Every direction call must quote a sentence from the Legislative Counsel’s digest of the bill. If the quoted sentence is not in the digest, the call is thrown away and shown as unclear.</p>
<h2>Who does the labelling</h2><p>An AI model ({esc(meta.get("model", ""))}) reads each bill’s title and digest and applies the list above. It is fast and cheap but not perfect: in a 50-bill test it agreed with a larger model on about 86% of direction calls. Bills without a digest are tagged from the title alone and usually come out unclear on direction. The model declined to process one bill (a biosecurity bill) and it is shown untagged. Labels are a guide to read the bill, not a substitute.</p>
<h2>Legislators</h2><p>Legislator pages count what each member authored or co-authored and how they voted on the floor, with every bill linked. Committee votes are not yet matched to members.</p>
<h2>Topics</h2><ul>{taxrows}</ul>"""))
    print(f"built {len(bills)} bill pages, {len(POLICY_TOPICS)} topic pages, {len(issue_data)} issue pages, {len(leg_rows)} legislator pages; {n_policy} bills with policy tags; {len(ceremonial)} ceremonial")


if __name__ == "__main__":
    sys.exit(main())
