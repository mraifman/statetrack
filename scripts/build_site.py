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
DOCS = ROOT / "docs"
STATES = json.loads((ROOT / "scripts/states.json").read_text(encoding="utf-8"))
ST, CFG = "CA", STATES["CA"]
DATA = ROOT / "data/ca"
OUT = DOCS / "ca"
SN = SX = SESS = SRC = DIG = ""
STATE_LIST = []   # [(code, name)] of states with data, for the state selector
HAS_FIND = HAS_VETOES = True


def set_state(code):
    global ST, CFG, DATA, OUT, SN, SX, SESS, SRC, DIG, BENCHMARK, ISSUES
    ST, CFG = code, STATES[code]
    f = ROOT / "scripts" / ("issues.json" if code == "CA" else f"issues_{code.lower()}.json")
    ISSUES = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"issues": [], "as_of": ""}
    DATA, OUT = ROOT / "data" / code.lower(), DOCS / code.lower()
    SN, SX, SESS, SRC = CFG.get("name_short") or CFG["name"], CFG["exec"], CFG["session"], CFG["source"]
    DIG = CFG["digest"][4:] if CFG["digest"].startswith("the ") else CFG["digest"]
    BENCHMARK = (f"Every direction is measured against the <b>status quo</b>: current {SN} law, as {CFG['digest']} describes it. "
                 "<b>Permissive</b> means the bill moves the law toward more permission, access or fewer rules. <b>Restrictive</b> means it moves toward less permission or more rules. "
                 "A bill that continues, studies or clarifies current law is neutral and is left out of the averages.")
TAX = json.loads((ROOT / "taxonomy/taxonomy.json").read_text())
SUB = {s["id"]: dict(s, topic_id=t["id"], topic=t["name"]) for t in TAX["topics"] for s in t["subtopics"]}
TOPICS = {t["id"]: t for t in TAX["topics"]}
EXCLUDED = {tid for tid, t in TOPICS.items() if t.get("excluded")}
POLICY_TOPICS = [tid for tid in TOPICS if tid not in EXCLUDED]
ISSUES = {"issues": [], "as_of": ""}
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


DEFS = json.loads((ROOT / "scripts/subtopic_defs.json").read_text(encoding="utf-8"))
for _t in TAX["topics"]:
    _t["name"] = T(_t["name"])
    for _s in _t["subtopics"]:
        _s["name"] = T(_s["name"])
        _d = DEFS.get(_s["id"].split(".", 1)[1])
        if _d:
            _s["note"] = f"Restrictive: {_d[0]}. Permissive: {_d[1]}."
        else:
            _s.pop("note", None)
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


def NOTE_DIV(n):
    return f'<div class="muted small">{esc(display_note(n))}</div>' if n else ""


def bsort(b):
    n = b.get("number")
    return (b.get("type", ""), int(n) if str(n).isdigit() else 0, str(n))


def disp_district(L):
    d = str(L.get("district", ""))
    m = re.match(r"^[A-Z]{2}0*(\d+)$", d)
    return m.group(1) if m else d


def official_link(b):
    href = CFG["official_bill_url"].format(id=b.get("id", ""), url=b.get("url", ""))
    return f'<p class="small"><a href="{esc(href)}">Official record on {esc(CFG["official_bill_label"])} ↗</a></p>' if href else ""


def dkey(v):
    """Comparable key for a district label; the same rule runs in the browser on the Census geocoder's answer."""
    v = str(v).strip()
    m = re.match(r"^(?:[A-Z]{2}|Ward\s+)0*(\d+)$", v)
    if m:
        return m.group(1)
    if v.isdigit():
        return str(int(v))
    words = sorted(w for w in re.findall(r"[a-z0-9]+", v.lower()) if w not in ("and", "the", "district"))
    return " ".join(words)


def dist_label(L):
    d = disp_district(L)
    return f"District {d}" if d.isdigit() else d


def SL(status):
    return {"Chaptered": "Became Law"}.get(status, status)


def RL(role):
    return {"LEAD_AUTHOR": "Lead author", "PRINCIPAL_COAUTHOR": "Principal co-author", "COAUTHOR": "Co-author"}.get(role, T(role))


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
BENCHMARK = ""

CSS_V = ""
CSS = """
:root{color-scheme:light;--bg:#ffffff;--surface:#ffffff;--alt:#f6f5f0;--ink:#161d2e;--ink2:#465065;--muted:#5b6577;--line:#e4e6ec;--axis:#c8ced9;--accent:#e0a500;--sun:#f2b705;--sun2:#f7d56a;--navy:#14213d;--navy2:#1f3157;
--rest2:#a62b1f;--rest1:#c8432f;--mixed:#9aa1b0;--neutral:#c9ced8;--perm1:#2a74bd;--perm2:#15508d;--chip:#eef0f5;--link:#15508d;
--serif:Charter,"Iowan Old Style","Palatino Linotype",Georgia,serif}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--link)}header.site{background:linear-gradient(180deg,var(--navy2),var(--navy));border-bottom:3px solid var(--sun);box-shadow:0 2px 14px rgba(20,33,61,.18)}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}header.site .wrap{max-width:1120px}nav{display:flex;gap:11px;align-items:center;flex-wrap:wrap;padding:12px 0;font-size:14.5px;white-space:nowrap}@media(max-width:1180px){nav .tag{display:none}}
nav .brand{font-family:var(--serif);font-weight:700;font-size:21px;letter-spacing:.2px;color:#fff;text-decoration:none;margin-right:4px;display:flex;align-items:center;gap:8px}nav .brand svg{width:24px;height:24px}nav .tag{color:var(--sun2);font-size:12.5px;letter-spacing:.14em;text-transform:uppercase;margin-right:12px;border-left:1px solid #4a5b82;padding-left:12px}nav a{color:#d6ddee;text-decoration:none}nav a:hover{color:#fff;text-decoration:none;box-shadow:0 2px 0 var(--sun)}
nav .toggle{margin-left:auto;font-size:14px;color:#d6ddee;display:flex;align-items:center;gap:6px;cursor:pointer}nav .toggle input{width:16px;height:16px}
.v-live{display:none}html.alive .v-live{display:revert}html.alive .v-all{display:none}html.alive .dead{display:none}
main{padding:24px 0 64px}h1{font-family:var(--serif);font-size:34px;line-height:1.15;letter-spacing:-.01em;margin:8px 0 8px;font-weight:700}h2{font-family:var(--serif);font-size:22px;margin:36px 0 10px;padding-top:14px;border-top:1px solid var(--line);font-weight:700}h3{font-size:16px;margin:20px 0 6px}
.lede{color:var(--ink2);max-width:70ch;margin:0 0 16px}.muted{color:var(--muted)}.small{font-size:14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:14px 16px;background:linear-gradient(180deg,#fff,var(--alt));box-shadow:0 1px 2px rgba(20,33,61,.06)}.tile b{display:block;font-family:var(--serif);font-size:30px;line-height:1.1;color:var(--navy)}.tile>span{color:var(--ink2);font-size:13px;text-transform:uppercase;letter-spacing:.06em}
.card{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:14px 16px;margin:12px 0;box-shadow:0 1px 2px rgba(20,33,61,.06);border-top:2px solid var(--navy)}
.issues{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin:12px 0}
.issues .card{margin:0;display:flex;flex-direction:column;gap:6px}.issues h3{margin:0;font-size:17px}.issues h3 a{font-family:var(--serif);color:var(--navy);text-decoration:none}.issues h3 a:hover{text-decoration:underline}
table{border-collapse:collapse;width:100%;font-size:15px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--ink2);font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:.03em}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.bars .row{display:grid;grid-template-columns:minmax(120px,230px) 1fr 56px;gap:10px;align-items:center;padding:3px 0}
.bars .track{height:16px}.bars .fill{height:100%;background:linear-gradient(90deg,var(--navy2),var(--navy));border-radius:0 3px 3px 0;min-width:2px}
.bars a{color:var(--ink);text-decoration:none}.bars a:hover{text-decoration:underline}.bars .v{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin:8px 0;font-size:14px;color:var(--ink2)}.legend span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px;background:var(--c)}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 9px;font-size:13px;color:var(--ink2);margin:1px 4px 1px 0;white-space:nowrap}
.chip.rest{background:var(--rest1);color:#fff}.chip.perm{background:var(--perm1);color:#fff}.chip.mid{background:var(--neutral);color:var(--ink)}
.dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:0}
.party{font-weight:600}.DEM{color:#2a78d6}.REP{color:#d03b3b}
blockquote{margin:6px 0;padding:8px 14px;border-left:3px solid var(--sun);color:var(--ink2);background:var(--alt);font-family:var(--serif)}
input[type=text],input:not([type]),select{font:inherit;padding:8px 10px;border:1px solid var(--axis);border-radius:4px;background:var(--surface);color:var(--ink)}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.filters input{flex:1;min-width:200px}
a[href*="bill/"]{white-space:nowrap}.bsum{margin:3px 0 2px;color:var(--ink2);font-size:15px;max-width:70ch}.bmeta{color:var(--muted);font-size:14px;margin-bottom:10px}.statecards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin:18px 0}.statecard{display:block;text-decoration:none;color:var(--ink)}.statecard h3{font-family:var(--serif);font-size:22px;margin:0 0 4px;color:var(--navy)}.mini3{display:flex;gap:18px;margin-top:10px}.mini3 b{display:block;font-family:var(--serif);font-size:24px;color:var(--navy)}.mini3 span{font-size:13px;color:var(--ink2);text-transform:uppercase;letter-spacing:.05em}.stsel{font:inherit;font-size:14px;padding:4px 8px;border-radius:4px;border:1px solid #4a5b82;background:#1f3157;color:#fff}details.subcat{margin:2px 0 2px 26px;padding-left:14px;border-left:3px solid var(--line)}details.subcat .mrow>span:first-child b{font-weight:600;font-size:15px}details.subcat .mrow>span:first-child b::before{content:"↳ ";color:var(--muted);font-weight:400}details.subcat table{font-size:15px}details.subcat>summary{display:block;list-style:none;cursor:pointer}details.subcat>summary::marker{content:""}details.subcat>summary:hover .mrow,details.subcat[open]>summary .mrow{background:var(--chip);border-radius:8px}details.cat>summary{display:block;list-style:none;cursor:pointer}details.cat>summary::marker{content:""}details.cat>summary::-webkit-details-marker{display:none}details.cat{border-bottom:1px solid var(--line);margin:0 0 4px;padding-bottom:6px}details.cat[open]>summary .mrow{background:var(--chip);border-radius:8px}details.cat>summary:hover .mrow{background:var(--chip);border-radius:8px}h3:target,h4:target{background:var(--chip);border-radius:6px;padding:2px 8px}details summary{cursor:pointer;color:var(--ink2)}footer{color:var(--muted);font-size:14px;padding:24px 0;border-top:1px solid var(--line)}
.axis{display:grid;grid-template-columns:minmax(120px,230px) 1fr 104px;gap:10px;font-size:13px;color:var(--ink2);margin-top:8px}.axis .ends{display:flex;justify-content:space-between}
.mrow{display:grid;grid-template-columns:minmax(120px,230px) 1fr 104px;gap:10px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line)}.mrow a{color:var(--ink);text-decoration:none}.mrow a:hover{text-decoration:underline}
.mrow .v{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2);font-size:14px}.mrow.sub{padding-left:14px}
.meter{position:relative;height:18px}.meter::before,.meter::after{content:"";position:absolute;top:7px;height:4px;width:50%}.meter::before{left:0;background:var(--rest1);opacity:.28;border-radius:2px 0 0 2px}.meter::after{right:0;background:var(--perm1);opacity:.28;border-radius:0 2px 2px 0}
.meter .mid{position:absolute;left:50%;top:1px;bottom:1px;width:2px;margin-left:-1px;background:var(--axis);z-index:1}
.meter .avg{position:absolute;top:3px;bottom:3px;width:3px;margin-left:-1.5px;background:var(--ink2);opacity:.7;z-index:1;border-radius:1px}
.meter .dot{position:absolute;top:1px;width:16px;height:16px;margin-left:-8px;border-radius:50%;border:2px solid var(--surface);z-index:2;box-shadow:0 0 0 1px var(--axis)}
.meter .dot.sg{width:18px;height:18px;margin-left:-9px;top:0;background:#fff;border:3px solid var(--navy);box-shadow:none;z-index:3}.meter .dot.vt{width:12px;height:12px;margin-left:-6px;top:3px;background:var(--navy);border:2px solid #fff;box-shadow:0 0 0 1px var(--navy);z-index:2}.gov .mrow,.gov .axis{grid-template-columns:minmax(120px,230px) 1fr}.gov .axis>span:last-child{display:none}.gov .legendrow{display:grid;grid-template-columns:minmax(120px,230px) 1fr;gap:10px}.gov .legend{justify-content:center;align-items:center;margin:12px 0}.gov .legend span{display:inline-flex;align-items:center}.gov .legend span::before{display:none}.gvl{white-space:nowrap;font-size:13px;margin:1px 0}.gvl .sym{color:var(--navy)}.legend .key{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:8px;flex:none}.legend .key.sg{border:3px solid var(--navy);background:#fff;width:14px;height:14px}.legend .key.vt{background:var(--navy)}.dot.rest{background:var(--rest1)}.dot.perm{background:var(--perm1)}.dot.mid{background:var(--neutral)}.dot.few{background:var(--surface);box-shadow:0 0 0 2px currentColor}.dot.few.rest{color:var(--rest1)}.dot.few.perm{color:var(--perm1)}.dot.few.mid{color:var(--mixed)}
.mini .meter{height:14px}.mini .meter .dot{width:12px;height:12px;margin-left:-6px;top:0}.mini .meter::before,.mini .meter::after{top:5px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}.note{border-left:3px solid var(--accent);padding:6px 12px;background:var(--surface)}
@media (max-width:640px){.bars .row{grid-template-columns:1fr 60px}.bars .track{grid-column:1/-1;order:3}.mrow,.axis{grid-template-columns:1fr 70px}.mrow .meter,.axis .ends{grid-column:1/-1;order:3}nav .toggle{margin-left:0}}
"""
import hashlib
CSS_V = "32b0faa0"   # frozen: changing it rewrites every page; bump only for a visible CSS change that must bypass caches


HEAD_JS = """<script>var d=document.documentElement;d.classList.add('alive');try{if(/[?&]dead=1/.test(location.search)||localStorage.getItem('st_show_dead')==='1')d.classList.remove('alive')}catch(e){}</script>"""
TOGGLE_JS = """<script>(function(){var c=document.getElementById('alive');if(!c)return;var r=document.documentElement;c.checked=!r.classList.contains('alive');
c.addEventListener('change',function(){r.classList.toggle('alive',!c.checked);try{localStorage.setItem('st_show_dead',c.checked?'1':'0')}catch(e){}window.dispatchEvent(new Event('alivechange'))})})();</script>"""


def slug(key):
    return re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")


def state_select(root):
    if len(STATE_LIST) < 2:
        return ""
    opts = "".join(f'<option value="{root}{c.lower()}/index.html"{" selected" if c == ST else ""}>{esc(n)}</option>' for c, n in STATE_LIST)
    return f'<select class="stsel" aria-label="State" onchange="location.href=this.value">{opts}</select>'


def page(title, body, depth=0, desc="", nav_compare=None):
    base = "../" * depth
    if nav_compare is None:
        nav_compare = depth == 0
    root = "../" * (depth + 1)
    body = body.replace("<table", '<div class="scroll"><table').replace("</table>", "</table></div>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · StateTrack</title><meta name="theme-color" content="#14213d"><meta name="description" content="{esc(desc or title)}"><link rel="stylesheet" href="{root}style.css?v={CSS_V}">{HEAD_JS}</head><body>
<header class="site"><div class="wrap"><nav><a class="brand" href="{root}index.html"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="6.5" fill="#f2b705"/><g stroke="#f2b705" stroke-width="2.2" stroke-linecap="round"><path d="M16 2.5v4M16 25.5v4M2.5 16h4M25.5 16h4M6.4 6.4l2.8 2.8M22.8 22.8l2.8 2.8M25.6 6.4l-2.8 2.8M9.2 22.8l-2.8 2.8"/></g></svg>StateTrack</a>{state_select(root)}<a href="{base}index.html">Overview</a>{f'<a href="{root}compare/index.html">Compare</a>' if nav_compare else ""}<a href="{base}bills.html">All bills</a>{f'<a href="{base}vetoes.html">Vetoes</a>' if HAS_VETOES else ""}
{f'<a href="{base}find.html">Find my legislators</a>' if HAS_FIND else ""}<a href="{base}legislators.html">Legislators</a><a href="{base}method.html">How it works</a>
<label class="toggle" title="Bills the official record marks as died, failed in committee or vetoed are hidden unless this is checked"><input type="checkbox" id="alive"> Show Bills that Died</label></nav></div></header>
<main><div class="wrap">{body}</div></main><footer><div class="wrap">Demo for {SN}’s {SESS} session. Bill data: {SRC}. Topics and directions are labelled by an AI model from the bill’s title and {CFG["digest"]}, and are approximate. <a href="{base}method.html">How it works</a></div></footer>{TOGGLE_JS}</body></html>"""


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
    tick = f'<i class="avg" style="left:{(avg + 2) / 4 * 100:.1f}%" title="all {SN} bills on this topic: {avg:+.2f}"></i>' if avg is not None else ""
    return (f'<div class="meter" role="img" aria-label="{esc(tip)}" title="{esc(tip)}"><i class="mid"></i>{tick}'
            f'<b class="dot {side}{" few" if n < MIN_TAGS else ""}" style="left:{pos:.1f}%"></b></div>'), mean


def load_votes(path):
    votes = json.load(gzip.open(path, "rt"))
    for vs in votes.values():
        for v in vs:
            if "floor" not in v:   # California's bulk file: location code like "AFLOOR"/"SFLOOR"/"CX28"
                v["floor"] = "FLOOR" in v.get("loc", "").upper()
                v["chamber"] = "Assembly" if v.get("loc", "").upper().startswith("A") else "Senate"
    return votes


def build_state(code):
    """Write docs/<code>/ for one state. Returns a summary used by the landing page."""
    global HAS_FIND, HAS_VETOES
    set_state(code)
    bills = json.loads((DATA / "bills.json").read_text())
    legislators = json.loads((DATA / "legislators.json").read_text())
    ov = DATA / "legislator_overrides.json"   # hand corrections to extracted legislator fields, keyed by legislator id
    if ov.exists():
        for lid_, fix in json.loads(ov.read_text(encoding="utf-8")).items():
            if lid_ in legislators:
                legislators[lid_].update(fix)
    for b_ in bills.values():   # DC adopts proposed resolutions; they are not laws
        if ST == "DC" and b_.get("type") == "PR" and b_["status"] == "Chaptered":
            b_["status"] = "Adopted"
    votes = load_votes(DATA / "votes.json.gz")
    history = json.load(gzip.open(DATA / "history.json.gz", "rt"))
    tagged = json.loads((DATA / "tags.json").read_text())["bills"]
    HAS_FIND = CFG.get("find", True)
    HAS_VETOES = any(b["status"] == "Vetoed" for b in bills.values())
    if OUT.exists():
        shutil.rmtree(OUT)
    for d in ("bill", "topic", "legislator", "issue", "data"):
        (OUT / d).mkdir(parents=True)

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
    lid_slug = {lid: slug(lid.split(":")[0] if ST == "CA" else lid) for lid in legislators}
    authored = defaultdict(list)
    for k, b in bills.items():
        for a in b.get("authors", []):
            if isinstance(a["legislator"], str):
                authored[a["legislator"]].append((k, a["role"]))
    cast = defaultdict(dict)
    for k, vs in votes.items():
        for v in vs:
            if not v["floor"]:
                continue
            for name, m in v["members"].items():
                lid = m.get("legislator")
                if isinstance(lid, str):
                    cur, stamp = cast[lid].get(k), (v["date"], int(v.get("seq") or 0))
                    if not cur or stamp >= cur[0]:
                        cast[lid][k] = (stamp, m["vote"])

    # ---------------- bill pages
    def author_line(b):
        out = []
        for a in b.get("authors", []):
            lid = a["legislator"]
            role = RL(a["role"])
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
        ev_first = {}
        for t in ts:
            ev_first.setdefault(t.get("evidence", ""), []).append(t)
        for t in ts:
            s = SUB[t["subtopic"]]
            d = t["direction"]
            g = group(d)
            dot = f'<span class="dot" style="background:var(--{g})"></span>' if g in ORDER else ""
            grp = ev_first[t.get("evidence", "")]
            if grp[0] is not t:
                ev = None
            else:
                ev = f'<blockquote>“{esc(t["evidence"])}”</blockquote>' if t.get("evidence") else '<span class="muted small">no quoted support</span>'
                if len(grp) > 1:
                    ev = ev.replace("</blockquote>", '<div class="muted small">Supports all ' + str(len(grp)) + ' tags in this group.</div></blockquote>', 1) if t.get("evidence") else ev
            evcell = "" if ev is None else f'<td rowspan="{len(grp)}">{ev}</td>'
            link = f'<a href="../topic/{s["topic_id"]}.html">{esc(s["topic"])}</a> → ' if s["topic_id"] not in EXCLUDED else ""
            rows.append(f'<tr><td>{link}{esc(s["name"])}</td><td>{dot}<b title="{esc(T(d))} (model wording)">{esc(DIR_WORD(d))}</b></td>'
                        f'<td>{esc(T(t["mechanism"]))}</td><td>{esc(T(t["funding"]))}</td><td>{esc(T(t["confidence"]))}</td>{evcell}</tr>')
        return ('<table><thead><tr><th>Topic → sub-topic</th><th>Direction vs. current law</th><th>Mechanism</th><th>Funding</th><th>Confidence</th><th>Quoted from the text</th></tr></thead><tbody>'
                + "".join(rows) + "</tbody></table>")

    def vote_block(k):
        vs = [v for v in votes.get(k, []) if v["floor"]]
        if not vs:
            return '<p class="muted">No recorded floor votes.</p>'
        out = []
        for v in sorted(vs, key=lambda v: (v["date"], int(v.get("seq") or 0))):
            by = defaultdict(list)
            for name, m in v["members"].items():
                by[m["vote"]].append(legislators[m["legislator"]]["name"].split(",")[0] if isinstance(m["legislator"], str) and m["legislator"] in legislators else name)
            lists = "".join(f'<p><b>{esc(c)}</b> ({len(n)}): {esc(", ".join(sorted(n)))}</p>' for c, n in sorted(by.items()))
            out.append(f'<details><summary>{esc(v["date"])} · {esc(v["chamber"])} floor · {esc(v["motion"][:90])} · {v["ayes"]}–{v["noes"]}'
                       f'{"–" + str(v["abstain"]) if v["abstain"] else ""} · {esc(v["result"])}</summary>{lists}</details>')
        return "".join(out)

    index = []
    for k, b in sorted(bills.items(), key=lambda kv: bsort(kv[1])):
        summary = tagged.get(k, {}).get("summary", "")
        if not tagged.get(k, {}).get("has_digest", True) or "text was provided" in summary:
            summary = "Not tagged: the Legislature published no summary for this measure, so its policy effect is not classified."
        hist_rows = "".join(f'<tr><td class="small">{esc(d)}</td><td>{esc(t)}</td></tr>' for d, _, t in history.get(k, [])[-25:][::-1])
        digest = esc(b.get("digest", "")) or '<span class="muted">No digest on file for this bill.</span>'
        body = f"""<p class="small"><a href="../bills.html">← All bills</a></p><h1>{esc(k)} · {esc(b.get("title", ""))}</h1>
<p class="lede">{esc(summary)}</p>
<div class="tiles"><div class="tile"><b style="font-size:18px">{esc(SL(b["status"]))}</b><span>Status</span></div><div class="tile"><b style="font-size:18px">{esc(b.get("last_action_date", ""))}</b><span>Last Action</span></div>
<div class="tile"><b style="font-size:18px">{esc(b.get("chapter", "")) if b["status"] == "Chaptered" else esc(b["house"])}</b><span>{"Chapter Number" if b["status"] == "Chaptered" else "Where It Ended" if b["status"] in ("Vetoed", "Died", "Failed", "Failed Passage in Committee") else "Currently In"}</span></div></div>
<p><b>Authors:</b> {author_line(b)}</p>
<h2>Topic tags</h2><p class="small muted">Direction is measured against current {SN} law as described in {CFG["digest_short"]}.</p>{tag_table(k)}
<h2>What the bill does ({esc(b.get("digest_source") or DIG)})</h2><div class="card small">{digest}</div>
<h2>Floor votes</h2>{vote_block(k)}
<h2>Recent actions</h2><table><tbody>{hist_rows}</tbody></table>
{official_link(b)}"""
        (OUT / "bill" / f"{slug(k)}.html").write_text(page(k, body, 1, summary or b.get("title", "")))
        index.append({"k": k, "s": slug(k), "t": b.get("title", ""), "st": b["status"],
                      "tp": sorted({SUB[t["subtopic"]]["topic_id"] for t in policy_tags[k]}),
                      "d": sorted({group(t["direction"]) for t in policy_tags[k] if group(t["direction"]) in ORDER}), "su": summary})

    def bill_li(k, extra="", depth=1, sid=None, brief=False):
        b = bills[k]
        sm = tagged.get(k, {}).get("summary", "")
        if not tagged.get(k, {}).get("has_digest", True) or "text was provided" in sm:
            sm = ""
        det = []
        if brief:
            return f'<li class="{"" if alive[k] else "dead"}"><a href="{"../" * depth}bill/{slug(k)}.html">{esc(k)}</a> · {esc(b.get("title", ""))} <span class="chip">{esc(SL(b["status"]))}</span>{extra}</li>'
        if sm:
            det.append(f'<div class="bsum">{esc(sm)}</div>')
        meta = []
        lead = next((a for a in b.get("authors", []) if isinstance(a["legislator"], str) and a["legislator"] in legislators), None)
        if lead:
            meta.append(f'Author: <a href="{"../" * depth}legislator/{lid_slug[lead["legislator"]]}.html">{esc(legislators[lead["legislator"]]["name"])}</a>')
        tg = next((x for x in btags.get(k, []) if sid and x["subtopic"] == sid), None)
        if tg and tg.get("mechanism") and tg["mechanism"] not in ("none", "other"):
            meta.append("Approach: " + esc(T(tg["mechanism"].replace("_", " "))))
        if b.get("last_action_date"):
            meta.append("Last action " + esc(b["last_action_date"]))
        if meta:
            det.append('<div class="bmeta">' + " · ".join(meta) + "</div>")
        return f'<li class="{"" if alive[k] else "dead"}"><a href="{"../" * depth}bill/{slug(k)}.html">{esc(k)}</a> · {esc(b.get("title", ""))} <span class="chip">{esc(SL(b["status"]))}</span>{extra}{"".join(det)}</li>'

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
            ks = sorted(sub_bills.get(s["id"], ()), key=lambda k: bsort(bills[k]))
            if not ks:
                continue
            td = {k: next((x["direction"] for x in btags[k] if x["subtopic"] == s["id"]), "") for k in ks}
            lis = "".join(bill_li(k, f' <span class="chip">{esc(DIR_WORD(td[k]))}</span>' if td[k] and td[k] != "not_applicable" else "", sid=s["id"]) for k in ks[:300])
            more = f'<p class="muted small">Showing the first 300 of {len(ks)}; use <a href="../bills.html">All bills</a> to search.</p>' if len(ks) > 300 else ""
            lists.append(f'<h3 id="{slug(s["id"])}">{esc(s["name"])} <span class="muted small">({vv(len(ks), len([k for k in ks if alive[k]]))})</span></h3><ul>{lis}</ul>{more}')
        n_all, n_live = len(topic_bills[tid]), len([k for k in topic_bills[tid] if alive[k]])
        body = (f'<p class="small"><a href="../index.html">← Overview</a></p><h1>{esc(t["name"])}</h1>'
                f'<p class="lede">{vv(n_all, n_live)} {SN} bills carry at least one tag under this topic. A bill can appear under several sub-topics.</p>'
                f'<div class="note small">{BENCHMARK}</div>{vb(block(False), block(True))}'
                f'<p class="small muted">Each marker is the average of its bills’ directions, from restrictive (−2) to permissive (+2). Neutral and unclear tags are left out; mixed counts as 0. A hollow marker means fewer than {MIN_TAGS} directional tags, so treat it as rough.</p>'
                + "".join(lists))
        (OUT / "topic" / f"{tid}.html").write_text(page(t["name"], body, 1, nav_compare=True))

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

    def au_link(k):
        lead = next((a for a in bills[k].get("authors", []) if a["role"] == "LEAD_AUTHOR" and isinstance(a["legislator"], str) and a["legislator"] in legislators), None)
        return f'<a href="legislator/{lid_slug[lead["legislator"]]}.html">{esc(legislators[lead["legislator"]]["name"])}</a>' if lead else "—"

    issue_cards, issue_data = [], []
    for iss in ISSUES["issues"]:
        ks = sorted((k for k in bills if issue_match(iss, k)), key=lambda k: bsort(bills[k]))
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
            return (f'<div class="small">{len(kk)} Bills · {c.get("Chaptered", 0)} Became Law'
                    f'{"" if live else " · " + str(c.get("Vetoed", 0)) + " Vetoed · " + str(sum(c.get(s, 0) for s in DEAD if s != "Vetoed")) + " Died"}</div><div class="mini">{m}</div>')
        issue_cards.append(f'<div class="card"><h3><a href="issue/{iss["id"]}.html">{esc(iss["name"])}</a></h3><div class="small muted">{esc(iss["hook"])}</div>{vb(card_stats(False), card_stats(True))}</div>')

        def issue_block(live, iss=iss, ks=ks):
            kk = [k for k in ks if not live or alive[k]]
            c = Counter(bills[k]["status"] for k in kk)
            active = sum(c.get(s, 0) for s in ("In Committee Process", "In Floor Process", "Passed", "Pending Referral"))
            tiles = (f'<div class="tiles"><div class="tile"><b>{len(kk)}</b><span>Bills</span></div><div class="tile"><b>{c.get("Chaptered", 0)}</b><span>Became Law</span></div>'
                     f'<div class="tile"><b>{c.get("Vetoed", 0)}</b><span>Vetoed</span></div>'
                     f'{"" if live else "<div class=tile><b>" + str(sum(c.get(s, 0) for s in DEAD)) + "</b><span>Died</span></div>"}'
                     f'<div class="tile"><b>{active}</b><span>Still Listed as Active</span></div></div>')
            sc = issue_scores(iss, ks, live)
            lean_html = ""
            if sc:
                m, mean = meter(sc, iss["name"])
                subs_ = set(iss["subtopics"]) or set()
                if iss.get("topic"):
                    subs_ = {x["id"] for x in TOPICS[iss["topic"]]["subtopics"]}
                by_sub = defaultdict(list)
                for k in kk:
                    for t in btags[k]:
                        if t["subtopic"] in subs_ and lean(t) is not None:
                            by_sub[t["subtopic"]].append((k, t))
                blocks = []
                for sid, its in sorted(by_sub.items(), key=lambda kv: -len(kv[1])):
                    ssc = [lean(t) for _, t in its]
                    smeter, smean = meter(ssc, SUB[sid]["name"])
                    sv = "Restrictive" if smean <= -CUT else "Permissive" if smean >= CUT else "Balanced"
                    sk = {"Restrictive": "rest", "Permissive": "perm", "Balanced": "mid"}[sv]
                    nb = len({k for k, _ in its})
                    rows_ = "".join(
                        f'<tr><td><a href="../bill/{slug(k)}.html">{esc(k)}</a> · {esc(bills[k].get("title", ""))}</td><td>{esc(SL(bills[k]["status"]))}</td>'
                        f'<td>{au_link(k).replace(chr(34) + "legislator/", chr(34) + "../legislator/")}</td><td>{esc(DIR_WORD(t["direction"]))}</td></tr>'
                        for k, t in sorted(its, key=lambda x: bsort(bills[x[0]])))
                    blocks.append(f'<details class="subcat"><summary><div class="mrow sub"><span><b>{esc(T(SUB[sid]["name"]))}</b> <span class="muted small">({nb} bill{"" if nb == 1 else "s"})</span>{NOTE_DIV(SUB[sid].get("note"))}</span>'
                                  f'{smeter}<div class="v"><span class="chip {sk}">{sv}</span><br><span class="muted small">{smean:+.2f}</span></div></div></summary>'
                                  f'<table><thead><tr><th>Bill</th><th>Status</th><th>Lead author</th><th>Direction vs. current law</th></tr></thead><tbody>{rows_}</tbody></table></details>')
                kind_ = "rest" if mean <= -CUT else "perm" if mean >= CUT else "mid"
                word_ = "Restrictive" if mean <= -CUT else "Permissive" if mean >= CUT else "Balanced"
                row_ = f'<div class="mrow"><span><b>{esc(iss["name"])}</b></span>{m}<div class="v"><span class="chip {kind_}">{word_}</span><br><span class="muted small">{mean:+.2f}</span></div></div>'
                lean_html = f'<h2>Where the bills lean</h2><p class="small muted">Click the row to see the sub-topics, then a sub-topic to see its bills.</p>{AXIS}<details class="cat"><summary>{row_}</summary>{"".join(blocks)}</details>'
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
        lis = "".join(bill_li(k) for k in sorted(ks, key=lambda k: (order.get(bills[k]["status"], 6), *bsort(bills[k])))[:400])
        body = (f'<p class="small"><a href="../index.html">← Overview</a></p><h1>{esc(iss["name"])}</h1><p class="lede">{esc(iss["hook"])}</p>'
                f'<p class="small muted">In the news ({esc(ISSUES["as_of"])}). Press coverage as found by search; open the sources for the full story:</p><ul class="small">{src}</ul>'
                f'<p class="small muted">Bills on this page: {"; ".join(scope)}.</p><div class="note small">{BENCHMARK}</div>{vb(issue_block(False), issue_block(True))}'
                f'<h2>Bills</h2><ul>{lis}</ul>')
        (OUT / "issue" / f"{iss['id']}.html").write_text(page(iss["name"], body, 1, iss["hook"], nav_compare=True))

    # ---------------- legislator pages
    leg_rows = []
    for lid, L in sorted(legislators.items(), key=lambda kv: kv[1]["name"]):
        au = authored.get(lid, [])
        vt = cast.get(lid, {})

        def leg_block(live, lid=lid, au=au, vt=vt):
            a_k = [(k, r) for k, r in au if not live or alive[k]]
            v_k = {k: v for k, v in vt.items() if not live or alive[k]}
            aye = sum(1 for _, v in v_k.values() if v == "AYE")
            noe = sum(1 for _, v in v_k.values() if v == "NOE")
            tiles = (f'<div class="tiles"><div class="tile"><b>{len(a_k):,}</b><span>Bills Authored or Co-authored</span></div><div class="tile"><b>{len(v_k):,}</b><span>Bills With a Recorded Floor Vote</span></div>'
                     f'<div class="tile"><b>{aye:,}</b><span>Aye Votes</span></div><div class="tile"><b>{noe}</b><span>No Votes</span></div></div>')
            # lean by issue (weighted authorship)
            per = defaultdict(list)
            for k, role in a_k:
                w = ROLE_WEIGHT.get(role, 1)
                for t in policy_tags[k]:
                    s = lean(t)
                    if s is not None:
                        per[SUB[t["subtopic"]]["topic_id"]].append((s, w, k, t, role))
            rows = []
            for tid, items in sorted(per.items(), key=lambda kv: -len(kv[1])):
                n = len(items)
                wm = sum(it[0] * it[1] for it in items) / sum(it[1] for it in items)
                if n < MIN_LEG:
                    chip, m = '<span class="chip">Not enough bills</span>', '<span class="muted small">fewer than 3 directional bills</span>'
                else:
                    m, _ = meter([wm], TOPICS[tid]["name"], topic_avg[tid][live])
                    m = m.replace('<b class="dot', '<b class="dot') if n >= MIN_TAGS else m
                    kind, word = ("rest", "Restrictive") if wm <= -CUT else ("perm", "Permissive") if wm >= CUT else ("mid", "Balanced")
                    chip = f'<span class="chip {kind}">{word}</span>'
                by_sid = defaultdict(list)
                for it in items:
                    by_sid[it[3]["subtopic"]].append(it)
                ordered = sorted(by_sid.items(), key=lambda kv: -len(kv[1]))
                driven = ", ".join(f'{esc(T(SUB[sid]["name"]))} ({len(v)})' for sid, v in ordered[:3]) + ("…" if len(ordered) > 3 else "")
                row = f'<div class="mrow"><span><b>{esc(TOPICS[tid]["name"])}</b></span>{m}<div class="v">{chip}<br><span class="muted small">{n} bill{"" if n == 1 else "s"}</span></div></div>'
                if n >= MIN_LEG:
                    blocks = []
                    for sid, its in ordered:
                        sw = sum(i[1] for i in its)
                        sm_ = sum(i[0] * i[1] for i in its) / sw
                        sv = "Restrictive" if sm_ <= -CUT else "Permissive" if sm_ >= CUT else "Balanced"
                        sk = {"Restrictive": "rest", "Permissive": "perm", "Balanced": "mid"}[sv]
                        smeter, _ = meter([sm_], SUB[sid]["name"])
                        sl = "".join(
                            f'<tr><td><a href="../bill/{slug(k)}.html">{esc(k)}</a> · {esc(bills[k].get("title", ""))}</td><td>{esc(RL(role))}</td><td>{esc(DIR_WORD(t["direction"]))}</td></tr>'
                            for sc, w, k, t, role in sorted(its, key=lambda it: (it[0], it[2])))
                        note_ = SUB[sid].get("note")
                        blocks.append(f'<details class="subcat"><summary><div class="mrow sub"><span><b>{esc(T(SUB[sid]["name"]))}</b> <span class="muted small">({len(its)} bill{"" if len(its) == 1 else "s"})</span>'
                                      f'{NOTE_DIV(note_)}</span>{smeter}<div class="v"><span class="chip {sk}">{sv}</span><br><span class="muted small">{sm_:+.2f}</span></div></div></summary>'
                                      f'<table><thead><tr><th>Bill</th><th>Role</th><th>Direction vs. current law</th></tr></thead><tbody>{sl}</tbody></table></details>')
                    tw = sum(it[1] for it in items)
                    tot = sum(it[0] * it[1] for it in items)
                    rows.append(f'<details class="cat"><summary>{row}</summary>{"".join(blocks)}<p class="small muted">Weighted average = {tot:+d} ÷ {tw} = <b>{wm:+.2f}</b></p></details>')
                else:
                    rows.append(row)
            lean_html = (f'<h2>Lean by issue</h2><p class="small muted">From the bills this legislator authored or co-authored. Each bill’s direction is measured against current law; lead authors count 3×, principal co-authors 2×, co-authors 1×. '
                         f'A tag needs at least {MIN_LEG} directional bills; <b>Restrictive</b> is a weighted average of −{CUT} or lower, <b>Permissive</b> is +{CUT} or higher, otherwise <b>Balanced</b>. '
                         f'The dark tick is the average of all {SN} bills on the topic. Click a topic to see the bills behind it.</p>{AXIS}{"".join(rows) if rows else "<p class=muted>No tagged bills with a direction.</p>"}')
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
            drows = "".join(f'<tr><td><a href="#t-{SUB[sid]["topic_id"]}">{esc(SUB[sid]["topic"])}</a> → <a href="#s-{slug(sid)}">{esc(SUB[sid]["name"])}</a></td><td class="n">{c["auR"]}</td><td class="n">{c["auP"]}</td><td class="n">{c["auN"]}</td>'
                            f'<td class="n">{c["ayR"]}</td><td class="n">{c["ayP"]}</td><td class="n">{c["noR"]}</td><td class="n">{c["noP"]}</td></tr>'
                            for sid, c in sorted(prof.items(), key=lambda kv: -sum(kv[1].values())))
            detail = ('<h2>Record by sub-topic</h2><table><thead><tr><th rowspan="2">Sub-topic</th><th colspan="3" class="n">Authored or Co-authored</th><th colspan="2" class="n">Voted Aye on</th><th colspan="2" class="n">Voted No on</th></tr>'
                      '<tr><th class="n">Restrictive</th><th class="n">Permissive</th><th class="n">Neutral or Mixed</th><th class="n">Restrictive</th><th class="n">Permissive</th><th class="n">Restrictive</th><th class="n">Permissive</th></tr></thead><tbody>'
                      + drows + "</tbody></table>") if drows else ""
            return tiles + lean_html + detail

        role_of = dict(au)
        by_topic = defaultdict(list)
        for k in set(role_of) | set(vt):
            for tid in {SUB[t["subtopic"]]["topic_id"] for t in policy_tags[k]}:
                by_topic[tid].append(k)
        sections = []
        for tid in POLICY_TOPICS:
            ks = by_topic.get(tid, [])
            if not ks:
                continue
            ks.sort(key=lambda k: (k not in role_of, role_of.get(k) != "LEAD_AUTHOR", *bsort(bills[k])))
            shown = ks[:max(40, sum(1 for k in ks if k in role_of))]
            groups = []
            for sub in TOPICS[tid]["subtopics"]:
                items = []
                for k in shown:
                    tg = [t for t in policy_tags[k] if t["subtopic"] == sub["id"]]
                    if not tg:
                        continue
                    chips = ""
                    if k in role_of:
                        chips += f' <span class="chip">{esc(RL(role_of[k]))}</span>'
                    if k in vt and vt[k][1] in ("AYE", "NOE"):
                        chips += f' <span class="chip">Voted {"Aye" if vt[k][1] == "AYE" else "No"}</span>'
                    if sub["axis"] in ("A", "R") and tg[0]["direction"] in SCORE:
                        chips += f' <span class="chip">{esc(DIR_WORD(tg[0]["direction"]))}</span>'
                    items.append(bill_li(k, chips, sid=sub["id"], brief=k not in role_of))
                if items:
                    groups.append(f'<h4 id="s-{slug(sub["id"])}">{esc(T(sub["name"]))} <span class="muted small">({len(items)})</span></h4><ul>{"".join(items)}</ul>')
            items = groups
            more = f'<p class="muted small">Showing {min(len(ks), max(40, sum(1 for k in ks if k in role_of)))} of {len(ks)}: all authored bills plus the first votes.</p>' if len(ks) > max(40, sum(1 for k in ks if k in role_of)) else ""
            n_all, n_live = len(ks), len([k for k in ks if alive[k]])
            sections.append(f'<h3 id="t-{tid}">{esc(TOPICS[tid]["name"])} <span class="muted small">({vv(n_all, n_live)})</span></h3>'
                            f'{"".join(items)}{more}<p class="small"><a href="../topic/{tid}.html">All {SN} bills on {esc(TOPICS[tid]["name"])} →</a></p>')
        record = f'<h2>Record by topic</h2><p class="small muted">Bills this legislator authored or co-authored first (with summaries), then bills they voted on. Direction chips are measured against current law.</p>{"".join(sections)}' if sections else ""
        au_sorted = sorted(au, key=lambda x: (x[1] != "LEAD_AUTHOR", *bsort(bills[x[0]])))
        au_list = "".join(bill_li(k, f' <span class="chip">{esc(RL(role))}</span>', brief=True) for k, role in au_sorted[:400])
        body = f"""<p class="small"><a href="../legislators.html">← All legislators</a></p><h1>{esc(L["name"])}</h1>
<p class="lede"><span class="party {L["party"]}">{esc({"DEM": "Democrat", "REP": "Republican"}.get(L["party"], L["party"]))}</span> · {esc(L["house"])} · {esc(dist_label(L))}{" · Former member" if not L.get("active", True) else ""}</p>
{vb(leg_block(False), leg_block(True))}
<p class="note small">These come from what this legislator authored and how they voted on tagged bills, with the bills linked below. A co-author may sign on to a bill they have reservations about, and a vote reflects one amendment stage. Most bills that reach a floor vote pass with large majorities and almost every member votes aye, so aye counts mostly mirror what reached the floor; authorship is the more distinctive signal. Treat the tags as a summary of the record, not a rating. Only floor votes are counted; committee votes are not matched to members yet.</p>
{record}
<h2>Bills authored ({len(au)})</h2><ul>{au_list}</ul>"""
        (OUT / "legislator" / f"{lid_slug[lid]}.html").write_text(page(L["name"], body, 1))
        leg_rows.append((L, lid, len(au), len([k for k, _ in au if alive[k]]), len(vt)))
    rows = "".join(f'<tr><td><a href="legislator/{lid_slug[lid]}.html">{esc(L["name"])}</a>{"" if L.get("active", True) else " <span class=muted>(former)</span>"}</td><td><span class="party {L["party"]}">{esc(L["party"])}</span></td><td>{esc(L["house"])}</td>'
                   f'<td>{esc(disp_district(L))}</td><td class="n">{vv(na, nal)}</td><td class="n">{nv}</td></tr>' for L, lid, na, nal, nv in leg_rows)
    lookup_note = "" if HAS_FIND else f' To find who represents you, use the <a href="{CFG["official_lookup"]}">{CFG["lookup_label"]}</a>.'
    (OUT / "legislators.html").write_text(page("Legislators", f'<h1>Legislators</h1><p class="lede">{len(leg_rows)} members of the {SESS} {SN} Legislature.{lookup_note}</p>'
        f'<table><thead><tr><th>Name</th><th>Party</th><th>House</th><th>District</th><th class="n">Bills authored</th><th class="n">Bills voted on (floor)</th></tr></thead><tbody>{rows}</tbody></table>'))

    # ---------------- find my legislators (street address -> Census geocoder -> districts; runs in the visitor's browser)
    if HAS_FIND:
        reps = {"L": {}, "U": {}, "X": []}
        extra = CFG.get("extra_districts", [])
        for L, lid, na, nal, nv in leg_rows:
            if not L.get("active", True):
                continue
            ch = "L" if L["house"] == CFG["lower"] else "U" if L["house"] == CFG.get("upper") else None
            if not ch:
                continue
            card_ = {"n": L["name"], "s": lid_slug[lid], "p": L["party"], "a": na, "d": dist_label(L)}
            if extra and L["district"] in extra:
                reps["X"].append(card_)
            else:
                reps[ch].setdefault(dkey(L["district"]), []).append(card_)
        find_js = """const REPS=__REPS__,LL=__LL__,UL=__UL__,LLY=__LLY__,ULY=__ULY__,XL=__XL__,OFF=__OFF__,OFFL=__OFFL__,SNAME=__SNAME__,STATE=__STATE__;
const BASE='https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress';
const box=document.getElementById('addr'),out=document.getElementById('res');
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function dkey(v){v=String(v).trim();let m=v.match(/^(?:[A-Z]{2}|Ward\\s+)0*(\\d+)$/);if(m)return m[1];if(/^\\d+$/.test(v))return String(parseInt(v,10));
return (v.toLowerCase().match(/[a-z0-9]+/g)||[]).filter(w=>!['and','the','district'].includes(w)).sort().join(' ')}
const PARTY={DEM:'Democrat',REP:'Republican'};
function card(r){return '<li class="card"><b><a href="legislator/'+r.s+'.html">'+esc(r.n.split(', ').reverse().join(' '))+'</a></b> <span class="party '+r.p+'">'+esc(PARTY[r.p]||r.p)+'</span><br><span class="muted small">'+esc(r.d)+' · '+r.a+' bills authored or co-authored</span></li>'}
function section(label,list){return list&&list.length?'<h2>'+label+'</h2><ul style="list-style:none;padding:0">'+list.map(card).join('')+'</ul>':''}
function lookup(addr){return new Promise((res,rej)=>{const cb='stcb'+Date.now();const s=document.createElement('script');
function done(){clearTimeout(t);delete window[cb];s.remove()}
const t=setTimeout(()=>{done();rej(new Error('timeout'))},25000);
window[cb]=d=>{done();res(d)};s.onerror=()=>{done();rej(new Error('network'))};
s.src=BASE+'?'+new URLSearchParams({address:addr,benchmark:'Public_AR_Current',vintage:'Current_Current',layers:'all',format:'jsonp',callback:cb});document.head.appendChild(s)})}
function layer(g,which){const k=Object.keys(g).find(x=>x.indexOf('State Legislative Districts - '+which)>=0);return k&&g[k][0]?(g[k][0].BASENAME||g[k][0].NAME):null}
async function go(){let raw=box.value.trim();
if(raw.length<6){out.innerHTML='<p class="note">Enter a street address and city, for example “1 Main St, Springfield”.</p>';return}
const q=/,\\s*[A-Za-z]{2}\\b/.test(raw)?raw:raw+', '+STATE;
history.replaceState(null,'','?address='+encodeURIComponent(raw));
out.innerHTML='<p class="muted">Looking up your districts…</p>';
let d;try{d=await lookup(q)}catch(e){out.innerHTML='<p class="note">The Census address lookup did not respond. Please try again, or use the <a href="'+OFF+'">'+OFFL+'</a>.</p>';return}
const m=d.result&&d.result.addressMatches&&d.result.addressMatches[0];
if(!m){out.innerHTML='<p class="note">The Census geocoder could not match that address. Check the street, city and ZIP, or use the <a href="'+OFF+'">'+OFFL+'</a>.</p>';return}
const g=m.geographies||{};let html='<p class="muted small">Matched address: <b>'+esc(m.matchedAddress)+'</b></p>';let found=false;
if(LLY){const k=layer(g,LLY);const list=k!==null?REPS.L[dkey(k)]:null;if(list){found=true;html+=section(LL,list)}}
if(ULY){const k=layer(g,ULY);const list=k!==null?REPS.U[dkey(k)]:null;if(list){found=true;html+=section(UL,list)}}
if(XL)html+=section(XL,REPS.X);
if(!found&&!XL)html+='<p class="note">That address matched, but no current '+SNAME+' member is on file for its district.</p>';
out.innerHTML=html+'<p class="note small">Your address went from your browser straight to the U.S. Census Bureau’s public geocoder, which returns the districts; this site does not receive or store it. Districts come from the Census Bureau’s 2026 maps. For an official answer use the <a href="'+OFF+'">'+OFFL+'</a>.</p>'}
document.getElementById('f').addEventListener('submit',e=>{e.preventDefault();go()});
const q0=new URLSearchParams(location.search).get('address');if(q0){box.value=q0;go()}""".replace("__REPS__", json.dumps(reps, separators=(",", ":"), ensure_ascii=False)).replace("__LLY__", json.dumps(CFG.get("lower_layer", "Lower"))).replace("__ULY__", json.dumps(CFG.get("upper_layer", "Upper") if CFG.get("upper") else None)).replace("__LL__", json.dumps(CFG.get("lower_label", ""))).replace("__UL__", json.dumps(CFG.get("upper_label", ""))).replace("__XL__", json.dumps(CFG.get("extra_label"))).replace("__OFFL__", json.dumps(CFG["lookup_label"])).replace("__OFF__", json.dumps(CFG["official_lookup"])).replace("__SNAME__", json.dumps(SN)).replace("__STATE__", json.dumps(ST))
        (OUT / "find.html").write_text(page("Find my legislators", f"""<h1>Find my legislators</h1>
<p class="lede">Enter your street address and city to see who represents you in the {SN} Legislature, then what each of them has authored and how they have voted.</p>
<form id="f" class="filters" autocomplete="off"><input id="addr" placeholder="Street address and city, e.g. 400 Main St, Springfield" aria-label="Street address and city" style="min-width:320px"><button type="submit" style="font:inherit;padding:7px 16px;border-radius:8px;border:0;background:var(--accent);color:#161d2e;cursor:pointer">Find</button></form>
<p class="muted small">Addresses are matched by the U.S. Census Bureau’s geocoder, called from your browser; StateTrack never sees them.</p>
<div id="res"></div><script>{find_js}</script>"""))

    # ---------------- vetoes tracker
    def veto_date(k):
        d = [x[0] for x in history.get(k, []) if re.search(r"\bveto(ed)?\b", x[2], re.I) and not re.search(r"pending|stricken|override|consideration|sustain", x[2], re.I)]
        return d[-1] if d else bills[k].get("last_action_date", "")

    def final_votes(k):
        out = {}
        for v in sorted((v for v in votes.get(k, []) if v["floor"]), key=lambda v: (v["date"], int(v.get("seq") or 0))):
            out[v["chamber"]] = (v["ayes"], v["noes"])
        return out

    def lead_party(k):
        for a in bills[k].get("authors", []):
            if a["role"] == "LEAD_AUTHOR" and isinstance(a["legislator"], str) and a["legislator"] in legislators:
                return legislators[a["legislator"]]["party"]
        return ""

    vetoed = sorted((k for k, b in bills.items() if b["status"] == "Vetoed"), key=lambda k: (veto_date(k), k), reverse=True)
    signed = [k for k, b in bills.items() if b["status"] == "Chaptered"]
    n_v, n_s = len(vetoed), len(signed)

    size = Counter(L["house"] for L in legislators.values() if L.get("active", True))
    two_chambers = bool(CFG.get("upper"))

    def proof(k):
        if not two_chambers:
            return False
        fv = final_votes(k)
        lo, up = CFG["lower"], CFG["upper"]
        return bool(fv.get(lo) and fv.get(up) and size[lo] and size[up] and fv[lo][0] * 3 >= 2 * size[lo] and fv[up][0] * 3 >= 2 * size[up])

    n_proof = sum(1 for k in vetoed if proof(k))

    def bill_topics(k):
        return sorted({SUB[t["subtopic"]]["topic_id"] for t in policy_tags[k]})

    def mean_lean(ks, tid=None):
        sc = [lean(t) for k in ks for t in policy_tags[k] if lean(t) is not None and (tid is None or SUB[t["subtopic"]]["topic_id"] == tid)]
        return (sum(sc) / len(sc), len(sc)) if sc else (None, 0)

    trows = []
    for tid in POLICY_TOPICS:
        v_k = [k for k in vetoed if tid in bill_topics(k)]
        s_k = [k for k in signed if tid in bill_topics(k)]
        if len(v_k) + len(s_k) < 10:
            continue
        mv, nv_ = mean_lean(v_k, tid)
        ms, ns_ = mean_lean(s_k, tid)
        fmt = lambda m, n: f"{m:+.2f}" if m is not None and n >= 3 else "n/a"
        trows.append((len(v_k) / (len(v_k) + len(s_k)), f'<tr><td><a href="topic/{tid}.html">{esc(TOPICS[tid]["name"])}</a></td><td class="n">{len(s_k)}</td><td class="n">{len(v_k)}</td><td class="n">{100 * len(v_k) / (len(v_k) + len(s_k)):.0f}%</td><td class="n">{fmt(ms, ns_)}</td><td class="n">{fmt(mv, nv_)}</td></tr>'))
    trows.sort(reverse=True)
    topic_tbl = ('<table><thead><tr><th>Topic</th><th class="n">Signed</th><th class="n">Vetoed</th><th class="n">Veto rate</th><th class="n">Avg. lean of signed</th><th class="n">Avg. lean of vetoed</th></tr></thead><tbody>'
                 + "".join(r for _, r in trows) + "</tbody></table>")
    def two_meter(ss, vs, label):
        def pos(sc):
            return (sum(sc) / len(sc) + 2) / 4 * 100
        dots = ""
        if vs:
            dots += f'<b class="dot vt" style="left:{pos(vs):.1f}%" title="Vetoed: average {sum(vs) / len(vs):+.2f} over {len(vs)} directional tags"></b>'
        if ss:
            dots += f'<b class="dot sg" style="left:{pos(ss):.1f}%" title="Signed: average {sum(ss) / len(ss):+.2f} over {len(ss)} directional tags"></b>'
        return f'<div class="meter" role="img" aria-label="{esc(label)}: signed and vetoed averages"><i class="mid"></i>{dots}</div>'

    def side_chip(sc, symbol, name):
        if len(sc) < MIN_LEG:
            return f'<div class="gvl"><span class="sym">{symbol}</span> {name} <span class="muted">n/a</span></div>'
        m_ = sum(sc) / len(sc)
        kind, word = ("rest", "Restrictive") if m_ <= -CUT else ("perm", "Permissive") if m_ >= CUT else ("mid", "Balanced")
        return f'<div class="gvl"><span class="sym">{symbol}</span> {name} <span class="chip {kind}">{word}</span></div>'

    def dir_scores(ks, pred):
        return [lean(t) for k in ks for t in policy_tags[k] if lean(t) is not None and pred(t)]

    def gov_detail(sk, vk, tid):
        by_sub = defaultdict(list)
        for status_, ks in (("Signed", sk), ("Vetoed", vk)):
            for k in ks:
                for t in policy_tags[k]:
                    if SUB[t["subtopic"]]["topic_id"] == tid and lean(t) is not None:
                        by_sub[t["subtopic"]].append((k, t, status_))
        out = []
        for sid, its in sorted(by_sub.items(), key=lambda kv: -len(kv[1])):
            ss = [lean(t) for _, t, st_ in its if st_ == "Signed"]
            vs = [lean(t) for _, t, st_ in its if st_ == "Vetoed"]
            rows_ = "".join(
                f'<tr><td><a href="bill/{slug(k)}.html">{esc(k)}</a> · {esc(bills[k].get("title", ""))}</td><td>{st_}</td><td>{au_link(k)}</td><td>{esc(DIR_WORD(t["direction"]))}</td></tr>'
                for k, t, st_ in sorted(its, key=lambda x: (x[2], *bsort(bills[x[0]]))))
            out.append(f'<details class="subcat"><summary><div class="mrow sub"><span><b>{esc(T(SUB[sid]["name"]))}</b> <span class="muted small">({len({k for k, _, _ in its})} bill{"" if len({k for k, _, _ in its}) == 1 else "s"})</span>{NOTE_DIV(SUB[sid].get("note"))}</span>'
                       f'{two_meter(ss, vs, SUB[sid]["name"])}</div></summary>'
                       f'<table><thead><tr><th>Bill</th><th>{SX}</th><th>Lead author</th><th>Direction vs. current law</th></tr></thead><tbody>{rows_}</tbody></table></details>')
        return "".join(out)

    def lean_row(label, ks, tid, avg, extra):
        row = lean_row_plain(label, ks, tid, avg, extra)
        sc = [lean(t) for k in ks for t in policy_tags[k] if lean(t) is not None and SUB[t["subtopic"]]["topic_id"] == tid] if tid else []
        if tid is None or len(sc) < MIN_LEG:
            return row
        return (f'<details class="cat"><summary>{row}</summary>{gov_detail(ks, tid)}'
                f'<p class="small muted">Average = {sum(sc):+d} ÷ {len(sc)} = <b>{sum(sc) / len(sc):+.2f}</b></p></details>')

    def lean_row_plain(label, ks, tid, avg, extra):
        sc = [lean(t) for k in ks for t in policy_tags[k] if lean(t) is not None and (tid is None or SUB[t["subtopic"]]["topic_id"] == tid)]
        if len(sc) < MIN_LEG:
            return f'<div class="mrow"><span>{label}</span><span class="muted small">fewer than {MIN_LEG} directional bills</span><div class="v">{extra}</div></div>'
        m, mean = meter(sc, re.sub('<[^>]+>', '', label), avg)
        kind, word = ("rest", "Restrictive") if mean <= -CUT else ("perm", "Permissive") if mean >= CUT else ("mid", "Balanced")
        return f'<div class="mrow"><span>{label}</span>{m}<div class="v"><span class="chip {kind}">{word}</span><br><span class="muted small">{extra}</span></div></div>'

    def gov_block():
        rows_ = []
        for tid in POLICY_TOPICS:
            sk = [k for k in signed if tid in bill_topics(k)]
            vk = [k for k in vetoed if tid in bill_topics(k)]
            pred = lambda t, tid=tid: SUB[t["subtopic"]]["topic_id"] == tid
            ss, vs = dir_scores(sk, pred), dir_scores(vk, pred)
            if not ss and not vs:
                continue
            rows_.append((len(ss) + len(vs), tid, sk, vk, ss, vs))
        out = []
        for _, tid, sk, vk, ss, vs in sorted(rows_, key=lambda r: -r[0]):
            row = (f'<div class="mrow"><span><b>{esc(TOPICS[tid]["name"])}</b></span>{two_meter(ss, vs, TOPICS[tid]["name"])}'
                   f'</div>')
            avg_s = f"{sum(ss) / len(ss):+.2f}" if ss else "n/a"
            avg_v = f"{sum(vs) / len(vs):+.2f}" if vs else "n/a"
            out.append(f'<details class="cat"><summary>{row}</summary>{gov_detail(sk, vk, tid)}<p class="small muted">Signed average = {avg_s} · Vetoed average = {avg_v}</p></details>')
        return AXIS + "".join(out)

    gov_html = '<div class="gov"><div class="legendrow"><span></span><div class="legend"><span style="--c:transparent"><i class="key sg"></i>Signed average</span><span style="--c:transparent"><i class="key vt"></i>Vetoed average</span></div></div>' + gov_block() + '</div>'

    prow = []
    for code_, name in (("DEM", "Democratic"), ("REP", "Republican")):
        v_k = [k for k in vetoed if lead_party(k) == code_]
        s_k = [k for k in signed if lead_party(k) == code_]
        if v_k or s_k:
            prow.append(f'<tr><td>{name} lead author</td><td class="n">{len(s_k)}</td><td class="n">{len(v_k)}</td><td class="n">{100 * len(v_k) / max(1, len(v_k) + len(s_k)):.0f}%</td></tr>')
    party_tbl = '<table><thead><tr><th>Bills by</th><th class="n">Signed</th><th class="n">Vetoed</th><th class="n">Veto rate</th></tr></thead><tbody>' + "".join(prow) + "</tbody></table>"

    def pole_share(ks):
        c = Counter(group(t["direction"]) for k in ks for t in policy_tags[k] if lean(t) is not None)
        tot = sum(c.values()) or 1
        r = (c["rest1"] + c["rest2"]) / tot
        p_ = (c["perm1"] + c["perm2"]) / tot
        return f"{100 * r:.0f}%", f"{100 * (1 - r - p_):.0f}%", f"{100 * p_:.0f}%", tot

    dr = []
    for label, ks in (("Signed into law", signed), ("Vetoed", vetoed)):
        a_, b_, c_, n_ = pole_share(ks)
        dr.append(f'<tr><td>{label}</td><td class="n">{a_}</td><td class="n">{b_}</td><td class="n">{c_}</td><td class="n">{n_:,}</td></tr>')
    dir_tbl = '<table><thead><tr><th></th><th class="n">Restrictive</th><th class="n">Mixed or Neutral</th><th class="n">Permissive</th><th class="n">Directional tags</th></tr></thead><tbody>' + "".join(dr) + "</tbody></table>"

    months = Counter(veto_date(k)[:7] for k in vetoed)
    mtop = max(months.values()) if months else 1
    month_bars = '<div class="bars">' + "".join(f'<div class="row"><span>{m}</span><div class="track"><div class="fill" style="width:{100 * n / mtop:.1f}%"></div></div><div class="v">{n}</div></div>' for m, n in sorted(months.items())) + "</div>"

    items = []
    for k in vetoed:
        b = bills[k]
        fv = final_votes(k)
        vt_txt = " · ".join(f'{h} {fv[h][0]}–{fv[h][1]}' for h in (CFG["lower"], CFG.get("upper")) if h in fv)
        tg = {}
        for t in policy_tags[k]:
            tg.setdefault(SUB[t["subtopic"]]["topic_id"], []).append(t)
        topic_chips = ""
        for tid, ts_ in tg.items():
            dirs = []
            for t in ts_:
                if lean(t) is not None and DIR_WORD(t["direction"]) not in dirs:
                    dirs.append(DIR_WORD(t["direction"]))
            topic_chips += f'<span class="chip">{esc(TOPICS[tid]["name"])}{": " + esc(", ".join(dirs)) if dirs else ""}</span>'
        sm = tagged.get(k, {}).get("summary", "")
        if not tagged.get(k, {}).get("has_digest", True) or "text was provided" in sm:
            sm = ""
        lead = next((a for a in b.get("authors", []) if a["role"] == "LEAD_AUTHOR" and isinstance(a["legislator"], str) and a["legislator"] in legislators), None)
        au = f'<a href="legislator/{lid_slug[lead["legislator"]]}.html">{esc(legislators[lead["legislator"]]["name"])}</a> ({esc(legislators[lead["legislator"]]["party"])})' if lead else "—"
        items.append(f'<li data-t="{" ".join(bill_topics(k))}"><a href="bill/{slug(k)}.html">{esc(k)}</a> · {esc(b.get("title", ""))}'
                     f'{" <span class=chip>Veto-proof margin in both houses</span>" if proof(k) else ""}'
                     f'<div class="bmeta">Vetoed {esc(veto_date(k))} · Author: {au} · {esc(vt_txt) or "no floor votes recorded"}</div>'
                     f'{f"<div class=bsum>{esc(sm)}</div>" if sm else ""}<div>{topic_chips}</div></li>')
    opts = "".join(f'<option value="{tid}">{esc(TOPICS[tid]["name"])}</option>' for tid in POLICY_TOPICS)
    vjs = """<script>const sel=document.getElementById('vt');sel.onchange=()=>{document.querySelectorAll('#vlist li').forEach(li=>{li.style.display=(!sel.value||li.dataset.t.split(' ').includes(sel.value))?'':'none'})}</script>"""
    (OUT / "vetoes.html").write_text(page(f"What is the {SX} vetoing?", f"""<h1>What is the {SX} vetoing?</h1>
<p class="lede">Of {n_v + n_s:,} bills that reached the {SX} in the {SESS} session, {n_v} were vetoed ({100 * n_v / (n_v + n_s):.1f}%) and {n_s:,} were signed. This page shows which topics, directions and authors the vetoes fall on.</p>
<div class="tiles"><div class="tile"><b>{n_v}</b><span>Vetoed</span></div><div class="tile"><b>{n_s:,}</b><span>Became Law</span></div><div class="tile"><b>{100 * n_v / (n_v + n_s):.1f}%</b><span>Veto Rate</span></div>{(f'<div class="tile"><b>{n_proof}</b><span>Vetoed After a Two-Thirds Vote in Both Houses</span></div>') if two_chambers else ""}</div>
<div class="note small">Direction compares each bill with current {SN} law, as everywhere else on this site. The {SX}’s veto messages (the stated reasons) are not part of this data; each bill shows its own summary and votes.</div>
<h2>Where the {SX} lands</h2><p class="small muted">On each topic, the hollow circle is the average direction of the bills the {SX} signed and the filled circle is the average of the bills the {SX} vetoed, measured against current law. Restrictive is −{CUT} or lower, Permissive is +{CUT} or higher, otherwise Balanced. Click a topic, then a sub-topic, to see the bills.</p>{gov_html}
<h2>By lead author’s party</h2>{party_tbl}
<h2>When</h2>{month_bars}
<h2>All {n_v} vetoed bills</h2><p><label class="small">Topic <select id="vt" aria-label="Topic"><option value="">All topics</option>{opts}</select></label></p><ul id="vlist">{"".join(items)}</ul>{vjs}""", 0, f"Bills vetoed by the {SX} in {SN}’s {SESS} session"))

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
    issues_html = (f'<h2>Issues in the news</h2><p class="small muted">Chosen from {SN} coverage as of {esc(ISSUES["as_of"])}. Each links to the bills, how they lean and who is authoring them.</p><div class="issues">{"".join(issue_cards)}</div>') if issue_cards else ""
    find_form = f'''<form class="filters" action="find.html" method="get"><input name="address" placeholder="Find my legislators: enter your street address and city" aria-label="Street address and city"><button type="submit" style="font:inherit;padding:7px 16px;border-radius:8px;border:0;background:var(--accent);color:#161d2e;cursor:pointer">Find</button></form>''' if HAS_FIND else ""
    find_li = '<li><a href="find.html">Find my legislators</a> by street address.</li>' if HAS_FIND else ""
    body = f"""<h1>{SN} legislation by topic and direction</h1>
<p class="lede">Every bill in {SN}’s {SESS} session, sorted into topics, with a read on which way each bill pushes against current law, Restrictive or Permissive, and where the money goes. Then what each legislator authored and how they voted.</p>
<div class="tiles"><div class="tile"><b>{vv(f"{len(bills):,}", f"{len(bills) - n_dead:,}")}</b><span>Bills</span></div><div class="tile"><b>{vv(f"{n_policy:,}", f"{sum(1 for k in bills if policy_tags[k] and alive[k]):,}")}</b><span>With Policy Topic Tags</span></div><div class="tile"><b>{len(leg_rows)}</b><span>Legislators</span></div>
<div class="tile"><b>{status.get("Chaptered", 0):,}</b><span>Became Law</span></div></div>
{find_form}
{issues_html}
<h2>How to read the meter</h2><div class="note small">{BENCHMARK} By default the site leaves out the {n_dead} bills the official record marks as died, failed in committee or vetoed. Bills still listed as in committee cannot pass once the session has ended, but they are only hidden if the record says they died.</div>
<h2>Where each topic leans</h2><p class="small muted">Each marker is the average direction of the bills tagged under that topic, from restrictive to permissive. Neutral and unclear tags are left out. A marker near the middle can hide a split: open the topic to see access and regulation separately.</p>{vb(topic_meters(False), topic_meters(True))}
<h2>Bills by topic</h2><p class="small muted">A bill counts once under each topic it touches, so bars add up to more than the number of bills. {len(ceremonial)} ceremonial or commemorative measures (naming, honoring) are not counted here.</p>{vb(topic_bars(False), topic_bars(True))}
<h2>Where to start</h2><ul><li><a href="bills.html">Search all bills</a> by words, topic, status or direction.</li>{find_li}<li><a href="legislators.html">Legislators</a>: a Restrictive / Permissive tag for each issue, plus authorship and floor votes.</li><li><a href="method.html">How it works</a>, and what the labels can and cannot tell you.</li></ul>"""
    (OUT / "index.html").write_text(page(f"{SN} by topic", body))

    # ---------------- bills search
    opts_t = "".join(f'<option value="{tid}">{esc(TOPICS[tid]["name"])}</option>' for tid in POLICY_TOPICS)
    opts_s = "".join(f'<option value="{esc(s)}">{esc(SL(s))}</option>' for s in sorted(status))
    opts_d = "".join(f'<option value="{g}">{GROUP_LABEL[g]}</option>' for g in ORDER)
    js = """const D=__D__;const TN=__TN__;const DEAD=__DEAD__;
const q=document.getElementById('q'),tp=document.getElementById('tp'),st=document.getElementById('st'),dr=document.getElementById('dr'),out=document.getElementById('out'),cnt=document.getElementById('cnt');
function esc(s){return s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function run(){const hide=document.documentElement.classList.contains('alive');const w=q.value.toLowerCase().trim().split(/\\s+/).filter(Boolean);let n=0,h='';
for(const b of D){if(hide&&DEAD.includes(b.st))continue;if(tp.value&&!b.tp.includes(tp.value))continue;if(st.value&&b.st!==st.value)continue;if(dr.value&&!b.d.includes(dr.value))continue;
const hay=(b.k+' '+b.t+' '+b.su).toLowerCase();if(w.some(x=>!hay.includes(x)))continue;n++;
if(n<=200)h+='<tr><td><a href="bill/'+b.s+'.html">'+esc(b.k)+'</a></td><td>'+esc(b.t)+'<div class="muted small">'+esc(b.su)+'</div></td><td>'+esc(({'Chaptered':'Became Law'})[b.st]||b.st)+'</td><td>'+b.tp.map(t=>'<span class="chip">'+esc(TN[t])+'</span>').join('')+'</td></tr>'}
out.innerHTML=h;cnt.textContent=n+' bills'+(n>200?' (showing the first 200; narrow the search)':'')}
[q,tp,st,dr].forEach(e=>e.addEventListener('input',run));window.addEventListener('alivechange',run);run();""".replace("__D__", json.dumps(index, separators=(",", ":"), ensure_ascii=False)).replace("__TN__", json.dumps({tid: TOPICS[tid]["name"] for tid in POLICY_TOPICS})).replace("__DEAD__", json.dumps(sorted(DEAD)))
    (OUT / "bills.html").write_text(page("All bills", f"""<h1>All bills</h1><p class="lede">Search {len(bills):,} {SN} bills.</p>
<div class="filters"><input id="q" placeholder="Search bill number, title or summary" aria-label="Search"><select id="tp" aria-label="Topic"><option value="">Any topic</option>{opts_t}</select>
<select id="st" aria-label="Status"><option value="">Any status</option>{opts_s}</select><select id="dr" aria-label="Direction"><option value="">Any direction</option>{opts_d}</select></div>
<p class="muted small" id="cnt"></p><table><thead><tr><th>Bill</th><th>Title</th><th>Status</th><th>Topics</th></tr></thead><tbody id="out"></tbody></table><script>{js}</script>"""))

    # ---------------- method
    taxrows = "".join(f'<li><b>{esc(t["name"])}</b>: ' + ", ".join(esc(s["name"]) for s in t["subtopics"]) + "</li>" for t in TAX["topics"] if not t.get("excluded"))
    find_method = '<h2>Find my legislators</h2><p>Enter a street address and the page asks the U.S. Census Bureau’s public geocoder which state legislative districts the address falls in, then shows the members for those districts. The request goes from your browser directly to the Census Bureau, so this site never sees or stores the address. District maps are the Census Bureau’s 2026 files; for an official answer use the state’s own lookup, linked on the page.</p>' if HAS_FIND else ""
    vetoes_method = f'''<h2>Vetoes</h2><p>The <a href="vetoes.html">Vetoes page</a> counts every bill that reached the {SX} in the {SESS} session. For each topic it shows the average direction of the bills signed and of the bills vetoed, on the same Restrictive / Permissive scale and measured against current law, so you can see what kind of bills get vetoed. Click a topic, then a sub-topic, to see the bills. The {SX}’s veto messages (the stated reasons) are not part of this data.</p>''' if HAS_VETOES else ""
    issues_method = f'''<h2>Issues in the news</h2><p>The issues on the overview were picked from news coverage as of {esc(ISSUES["as_of"])}. Each issue page lists its sources and states exactly which bills it includes (by tag and by wording in the title or digest). Keyword matching can include a bill that only mentions the subject in passing.</p>''' if issue_data else ""
    meta = json.loads((DATA / "tags.json").read_text())
    (OUT / "method.html").write_text(page("How it works", f"""<h1>How it works</h1>
<h2>The benchmark: current law</h2><p>{BENCHMARK}</p>
<h2>What is labelled</h2><p>Each {SN} bill gets one or more tags. A tag has a <b>sub-topic</b> from a fixed two-level list ({len(POLICY_TOPICS)} topics, {sum(len(TOPICS[t]["subtopics"]) for t in POLICY_TOPICS)} sub-topics, version {esc(TAX["version"])}), a <b>direction</b> against the status quo, a <b>mechanism</b> (a ban, a licensing rule, a tax incentive, a study) and a <b>funding</b> note (increases, decreases, none). Ceremonial measures (naming, honoring) are tagged as “not a policy topic” and left out of the charts.</p>
<h2>Direction</h2><p>Every bill is labelled Restrictive, Permissive, Mixed or Neutral on each sub-topic it touches, with “Strongly” where the change is large. The AI model’s own wording differs by sub-topic (expands or restricts for access and rights, tightens or loosens for regulation); the site maps both to Permissive and Restrictive, and the original word appears as a tooltip. Funding-only sub-topics have no direction. Studies, assessments, voluntary programs and rules that only assign responsibility are Neutral. Direction describes what a bill does, not whether that is good or bad.</p>
<h2>The restrictive-to-permissive meter</h2><p>Each directional tag is scored: Strongly Restrictive −2, Restrictive −1, Mixed 0, Permissive +1, Strongly Permissive +2. A marker sits at the average. Neutral, unclear and funding-only tags are left out, and a hollow marker means fewer than {MIN_TAGS} directional tags. The average hides disagreement inside a topic, so topic pages show access and regulation separately.</p>
<h2>Show Bills that Died</h2><p>By default the site leaves out bills whose official status is “Died”, “Failed Passage in Committee” or “Vetoed” from every count, meter and list. Check <b>Show Bills that Died</b> in the header to include them. A bill still shown as “in committee” after the session ended cannot pass, but it is not hidden unless the record marks it as died.</p>
<h2>Legislator tags</h2><p>On each legislator’s page, every issue gets a <b>Restrictive</b>, <b>Permissive</b> or <b>Balanced</b> tag from the bills they authored or co-authored. Lead authors count 3×, principal co-authors 2× and co-authors 1×. A tag needs at least {MIN_LEG} directional bills; a weighted average of −{CUT} or lower is Restrictive and +{CUT} or higher is Permissive. The tag describes the bills, not the person’s views, and co-authors sometimes sign on without strong support. The dark tick on each meter marks the average of all {SN} bills on that topic.</p>
{issues_method}
<h2>Bill status</h2><p>Statuses come from the Legislature’s record. <b>Became Law</b> means the bill was chaptered: the {SX} signed it, or it became law without a signature, and it has a chapter number. <b>Vetoed</b> bills were returned by the {SX}. <b>Died</b> and <b>Failed Passage in Committee</b> bills did not advance.</p>
{vetoes_method}
<h2>Autonomous vehicles and driver assistance</h2><p>These are separate sub-topics. <b>Autonomous vehicles</b> covers driverless or automated driving systems that operate without a human driver continuously in control. <b>Driver-assistance systems (ADAS)</b> covers partially automated features where a human must stay in control, such as lane-keeping and adaptive cruise control. A drunk-driving or other traffic offense by a human using these features is filed under Traffic safety unless the bill regulates the feature itself.</p>
{find_method}<h2>Reading legislator pages</h2><p>Click a topic to see that legislator’s sub-topics, each with its own score, and click a sub-topic to see the bills behind it, with their role and direction. The label on a topic is a summary of those sub-topic scores.</p>
<h2>Evidence</h2><p>Every direction call must quote a sentence from the bill’s title or {CFG["digest"]}. If the quoted sentence is not in the digest, the call is thrown away and shown as unclear.</p>
<h2>Who does the labelling</h2><p>An AI model ({esc(meta.get("model", ""))}) reads each bill’s title and digest and applies the list above. It is fast and cheap but not perfect: in a 50-bill test it agreed with a larger model on about 86% of direction calls. Bills without a digest are tagged from the title alone and usually come out unclear on direction. The model declined to process one bill (a biosecurity bill) and it is shown untagged. Labels are a guide to read the bill, not a substitute.</p>
<h2>Legislators</h2><p>Legislator pages count what each member authored or co-authored and how they voted on the floor, with every bill linked. Committee votes are not yet matched to members.</p>
<h2>Topics</h2><ul>{taxrows}</ul>"""))
    print(f"built {len(bills)} bill pages, {len(POLICY_TOPICS)} topic pages, {len(issue_data)} issue pages, {len(leg_rows)} legislator pages; {n_policy} bills with policy tags; {len(ceremonial)} ceremonial")
    if not HAS_VETOES and (OUT / "vetoes.html").exists():
        (OUT / "vetoes.html").unlink()
    return {"code": code, "name": CFG["name"], "short": SN, "bills": len(bills), "tagged": n_policy, "legislators": len(leg_rows),
            "laws": status.get("Chaptered", 0), "vetoed": status.get("Vetoed", 0), "chambers": [CFG["lower"]] + ([CFG["upper"]] if CFG.get("upper") else []),
            "session": SESS}


def landing(summaries):
    cards = "".join(
        f'<a class="card statecard" href="{x["code"].lower()}/index.html"><h3>{esc(x["short"] if x["short"] == "DC" else x["name"])}</h3>'
        f'<div class="small muted">{esc(x["session"])} session · {esc(" and ".join(x["chambers"]))}</div>'
        f'<div class="tiles mini3"><div><b>{x["bills"]:,}</b><span>Bills</span></div><div><b>{x["laws"]:,}</b><span>Became Law</span></div><div><b>{x["legislators"]}</b><span>Legislators</span></div></div></a>'
        for x in summaries)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StateTrack</title><meta name="theme-color" content="#14213d"><meta name="description" content="State bills sorted by topic and by which way they push against current law."><link rel="stylesheet" href="style.css?v={CSS_V}"></head><body>
<header class="site"><div class="wrap"><nav><a class="brand" href="index.html"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="6.5" fill="#f2b705"/><g stroke="#f2b705" stroke-width="2.2" stroke-linecap="round"><path d="M16 2.5v4M16 25.5v4M2.5 16h4M25.5 16h4M6.4 6.4l2.8 2.8M22.8 22.8l2.8 2.8M25.6 6.4l-2.8 2.8M9.2 22.8l-2.8 2.8"/></g></svg>StateTrack</a></nav></div></header>
<main><div class="wrap"><h1>State legislation by topic and direction</h1>
<p class="lede">Every bill in each state’s 2025–26 session, sorted into topics, with a read on which way it pushes against current law, Restrictive or Permissive, plus what each legislator authored and how they voted. Pick a state.</p>
<a class="card" href="compare/index.html" style="display:block;text-decoration:none;color:inherit;margin:14px 0"><h3 style="font-family:var(--serif);font-size:22px;margin:0 0 4px;color:var(--navy)">Compare states →</h3><div class="small">The same topics side by side with sub-topic detail, matching bills across states, a timeline, enactment gaps, bipartisan sponsorship, governors, pending bills and CSV downloads.</div></a>
<div class="statecards">{cards}</div>
<p class="small muted">Topics and directions are labelled by an AI model from each bill’s title and official summary, and are approximate. Each state’s <em>How it works</em> page explains the method.</p></div></main></body></html>"""


def main():
    codes = [c for c in STATES if (ROOT / "data" / c.lower() / "tags.json").exists() and (ROOT / "data" / c.lower() / "bills.json").exists()]
    codes.sort(key=lambda c: (c != "CA", STATES[c]["name"]))
    only = [a.upper() for a in sys.argv[1:]]
    global STATE_LIST
    STATE_LIST = [(c, STATES[c].get("name_short") or STATES[c]["name"]) for c in codes]
    DOCS.mkdir(exist_ok=True)
    (DOCS / ".nojekyll").write_text("")
    (DOCS / "style.css").write_text(CSS)
    summaries = []
    for c in codes:
        if only and c not in only:
            summaries.append(json.loads((DOCS / c.lower() / "summary.json").read_text()))
            continue
        x = build_state(c)
        (DOCS / c.lower() / "summary.json").write_text(json.dumps(x))
        summaries.append(x)
    (DOCS / "index.html").write_text(landing(summaries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
