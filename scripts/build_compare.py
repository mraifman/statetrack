#!/usr/bin/env python3
"""Cross-state pages for StateTrack: compare topics and sub-topics, matching bills, timeline, enactment gap,
bipartisan sponsorship, governors, pending bills and data downloads. Writes docs/compare/ and docs/data/."""
import csv, hashlib, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_data as cd
import compare_match as cm
import build_site as bs

ROOT = cd.ROOT
OUT = ROOT / "docs" / "compare"
DATA_OUT = ROOT / "docs" / "data"
esc = bs.esc
SUB, TOPICS, POLICY_TOPICS = cd.SUB, cd.TOPICS, cd.POLICY_TOPICS
STATE_COLOR = {"CA": "#2a78d6", "FL": "#d9561f", "MA": "#13876a", "OR": "#b07a00", "DC": "#6250d6", "WA": "#2f7d1f"}
MIN_DIR = 3      # fewer directional tags than this: no marker
MIN_FIRM = 8     # fewer than this: drawn faint, "rough"

CCSS = """
.cmp-tabs{display:flex;flex-wrap:wrap;gap:6px 18px;margin:4px 0 18px;padding:0;list-style:none}
.cmp-tabs a{font-weight:600;text-decoration:none;color:var(--navy);padding:4px 0;border-bottom:2px solid transparent}
.cmp-tabs a:hover,.cmp-tabs a.on{border-bottom-color:var(--sun)}
.grid-note{font-size:14px;color:var(--ink2);margin:6px 0 14px;max-width:80ch}
table.heat{border-collapse:separate;border-spacing:3px;width:100%}
table.heat th{font-size:13px;color:var(--ink2);text-transform:none;letter-spacing:0;text-align:center;border:0;padding:4px}
table.heat th:first-child,table.heat td:first-child{text-align:left}
table.heat td{border:0;border-radius:6px;padding:8px 6px;text-align:center;vertical-align:middle;min-width:84px}
table.heat td.rowh{padding-left:2px;background:none}
table.heat td b{display:block;font-size:16px;font-family:var(--serif)}
table.heat td span.n{display:block;font-size:12.5px;color:var(--ink2)}
table.heat td.faint{opacity:.55}
table.heat td.na{background:#f3f2ee;color:var(--muted)}
.sdot{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;color:#fff;font-size:11px;font-weight:700;vertical-align:middle}
.strip{position:relative;height:54px}
.strip::before,.strip::after{content:"";position:absolute;top:25px;height:4px;width:50%}
.strip::before{left:0;background:var(--rest1);opacity:.28;border-radius:2px 0 0 2px}.strip::after{right:0;background:var(--perm1);opacity:.28;border-radius:0 2px 2px 0}
.strip .mid{position:absolute;left:50%;top:14px;bottom:14px;width:2px;margin-left:-1px;background:var(--axis);z-index:1}
.strip .sdot{position:absolute;top:2px;margin-left:-11px;z-index:2;border:2px solid #fff;box-shadow:0 0 0 1px rgba(20,33,61,.25);width:22px;height:22px}
.strip .sdot.faint{opacity:.45}
.legend-s{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:14px;color:var(--ink2);margin:8px 0}
.axis.cmpaxis{grid-template-columns:minmax(150px,260px) 1fr 220px}
.srow{display:grid;grid-template-columns:minmax(150px,260px) 1fr 220px;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}
.srow .cnt{font-size:13px;color:var(--ink2);text-align:right}
.mcard{border:1px solid var(--line);border-top:2px solid var(--navy);border-radius:6px;padding:12px 16px;margin:14px 0;background:#fff}
.mcard .mhead{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;margin-bottom:6px}
.mcard table td{font-size:15px}
.tag-strong{background:var(--navy);color:#fff}.tag-related{background:var(--chip)}
.bar2{display:inline-block;height:10px;background:var(--navy);border-radius:2px;vertical-align:middle}
.tl-row{display:grid;grid-template-columns:130px 1fr;gap:12px;align-items:center;margin:6px 0}
.tl-row svg{width:100%;height:78px;display:block}
.tl-meta{font-size:14px;color:var(--ink2)}
.filters label{font-size:14px;color:var(--ink2);display:flex;align-items:center;gap:6px}
.fbar{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;margin:10px 0 16px}
.seq0{background:#f6f5f0}
@media(max-width:700px){.srow{grid-template-columns:1fr}.tl-row{grid-template-columns:1fr}}
"""
CCSS_V = hashlib.md5(CCSS.encode()).hexdigest()[:8]

TABS = [("index.html", "By topic"), ("matches.html", "Matching bills"), ("timeline.html", "Timeline"), ("enactment.html", "Enactment gap"),
        ("bipartisan.html", "Bipartisan"), ("governors.html", "Governors"), ("pending.html", "Pending bills"), ("data.html", "Data")]


AXIS_C = '<div class="axis cmpaxis"><span></span><div class="ends"><span>← Restrictive</span><span>Permissive →</span></div><span></span></div>'


def state_name(c):
    return cd.STATES[c].get("name_short") or cd.STATES[c]["name"]


def cpage(title, body, depth, active="index.html", desc=""):
    root = "../" * depth
    tabs = "".join(f'<li><a href="{root}compare/{h}"{" class=on" if h == active else ""}>{esc(n)}</a></li>' for h, n in TABS)
    sel = "".join(f'<option value="{root}{c.lower()}/index.html">{esc(state_name(c))}</option>' for c in STATE_ORDER)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · StateTrack</title><meta name="theme-color" content="#14213d"><meta name="description" content="{esc(desc or title)}"><link rel="stylesheet" href="{root}style.css?v={bs.CSS_V}"><link rel="stylesheet" href="{root}compare.css?v={CCSS_V}"></head><body>
<header class="site"><div class="wrap"><nav><a class="brand" href="{root}index.html"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="6.5" fill="#f2b705"/><g stroke="#f2b705" stroke-width="2.2" stroke-linecap="round"><path d="M16 2.5v4M16 25.5v4M2.5 16h4M25.5 16h4M6.4 6.4l2.8 2.8M22.8 22.8l2.8 2.8M25.6 6.4l-2.8 2.8M9.2 22.8l-2.8 2.8"/></g></svg>StateTrack</a>
<a href="{root}compare/index.html">Compare states</a><select class="stsel" aria-label="Go to a state" onchange="if(this.value)location.href=this.value"><option value="">Go to a state…</option>{sel}</select></nav></div></header>
<main><div class="wrap"><ul class="cmp-tabs">{tabs}</ul>{body}</div></main>
<footer><div class="wrap">Cross-state view of {len(STATE_ORDER)} states’ 2025–26 sessions. Topics and directions are labelled by an AI model from each bill’s title and official summary, and are approximate. Sessions differ in length and in how bills die, so compare with care.</div></footer></body></html>"""


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def fmt(m):
    return "n/a" if m is None else f"{m:+.2f}".replace("-", "−")


def lean_style(m):
    if m is None:
        return ""
    a = min(1.0, abs(m)) * 0.55
    rgb = "200,67,47" if m < 0 else "42,116,189"
    return f"background:rgba({rgb},{a:.2f})"


def seq_style(x, hue="20,33,61"):
    return f"background:rgba({hue},{min(1.0, x) * 0.6 + 0.04:.2f})"


def sdot(c, extra="", style=""):
    return f'<span class="sdot{extra}" style="background:{STATE_COLOR[c]};{style}" title="{esc(state_name(c))}">{c}</span>'


def legend():
    return '<div class="legend-s">' + "".join(f'<span>{sdot(c)} {esc(state_name(c))}</span>' for c in STATE_ORDER) + "</div>"


def bill_href(c, b, depth):
    return f'{"../" * depth}{c.lower()}/bill/{b["slug"]}.html'


# ------------------------------------------------------------------ stats
def collect(A):
    """per (state, subtopic) and (state, topic): bills, directional scores, law counts"""
    sub = defaultdict(lambda: {"bills": set(), "dir": [], "law": set(), "law_dir": []})
    top = defaultdict(lambda: {"bills": set(), "dir": [], "law": set(), "law_dir": []})
    for c, S in A.items():
        for k, b in S["bills"].items():
            for t in b["tags"]:
                tid = SUB[t["subtopic"]]["topic_id"]
                for bucket in (sub[(c, t["subtopic"])], top[(c, tid)]):
                    bucket["bills"].add(k)
                    if t["lean"] is not None:
                        bucket["dir"].append(t["lean"])
                    if b["status"] == "Chaptered":
                        bucket["law"].add(k)
                        if t["lean"] is not None:
                            bucket["law_dir"].append(t["lean"])
    return sub, top


# ------------------------------------------------------------------ 1. by topic / sub-topic
FEATURED = ["housing.zoning_land_use_and_short_term_rentals", "housing.rent_regulation_and_tenant_protections",
            "environment_and_energy.clean_energy", "environment_and_energy.utility_regulation_and_rates",
            "health_care.reproductive_health_and_abortion", "health_care.public_health_vaccines_and_emergency_measures",
            "health_care.gender_affirming_and_transgender_health_care",
            "criminal_justice.drug_policy", "criminal_justice.policing_and_accountability",
            "labor_and_employment.minimum_wage_and_wage_rules", "labor_and_employment.unions_and_collective_bargaining",
            "ai_and_technology.data_privacy_and_security", "children_and_families.kids_online_safety_and_age_verification",
            "guns_and_weapons.purchase_licensing_and_dealers", "immigration.state_cooperation_with_federal_enforcement_including_employment_verification",
            "elections_and_voting.voter_registration_and_access", "consumer_protection_and_business.alcohol_tobacco_and_vaping",
            "consumer_protection_and_business.gambling_and_sports_betting", "government_and_administration.local_control_and_preemption",
            "education.curriculum_and_classroom_content"]


def matrix_cells(d_by_state, bills_by_state):
    cells = []
    for c in STATE_ORDER:
        d, nb = d_by_state[c], bills_by_state[c]
        if len(d) < MIN_DIR:
            cells.append(f'<td class="na">n/a<span class="n">{nb:,} {"bill" if nb==1 else "bills"}</span></td>')
        else:
            m = mean(d)
            cells.append(f'<td class="{"faint" if len(d) < MIN_FIRM else ""}" style="{lean_style(m)}"><b>{fmt(m)}</b><span class="n">{nb:,} {"bill" if nb==1 else "bills"}</span></td>')
    return "".join(cells)


def page_hub(A, top):
    head = "".join(f'<th>{sdot(c)}<br>{esc(state_name(c))}</th>' for c in STATE_ORDER)
    sub = HUB_SUB
    srows = []
    for sid in FEATURED:
        s_ = SUB[sid]
        cells = matrix_cells({c: sub[(c, sid)]["dir"] for c in STATE_ORDER}, {c: len(sub[(c, sid)]["bills"]) for c in STATE_ORDER})
        srows.append(f'<tr><td class="rowh"><a href="sub/{bs.slug(sid)}.html"><b style="display:inline;font-family:inherit;font-size:16px">{esc(bs.T(s_["name"]))}</b></a>'
                     f'<br><a class="muted small" href="topic/{s_["topic_id"]}.html">{esc(s_["topic"])}</a></td>{cells}</tr>')
    rows = []
    for tid in POLICY_TOPICS:
        has_dir = any(sb["axis"] in ("A", "R") for sb in TOPICS[tid]["subtopics"])
        if has_dir:
            cells = matrix_cells({c: top[(c, tid)]["dir"] for c in STATE_ORDER}, {c: len(top[(c, tid)]["bills"]) for c in STATE_ORDER})
        else:
            cells = "".join(f'<td class="na">no scale<span class="n">{len(top[(c, tid)]["bills"]):,} bills</span></td>' for c in STATE_ORDER)
        rows.append(f'<tr><td class="rowh"><a href="topic/{tid}.html"><b style="display:inline;font-family:inherit;font-size:16px">{esc(TOPICS[tid]["name"])}</b></a></td>{cells}</tr>')
    browse = "".join(f'<details class="cat"><summary><div class="srow" style="grid-template-columns:1fr"><a href="topic/{tid}.html"><b>{esc(TOPICS[tid]["name"])}</b></a></div></summary><ul>' +
                     "".join(f'<li><a href="sub/{bs.slug(sb["id"])}.html">{esc(bs.T(sb["name"]))}</a></li>' for sb in TOPICS[tid]["subtopics"]) + "</ul></details>" for tid in POLICY_TOPICS)
    body = f"""<h1>Compare states</h1>
<p class="lede">The same issues, side by side. Each number is the average direction of a state’s bills on a sub-topic, from −2 (Restrictive) to +2 (Permissive), measured against that state’s current law. Click a sub-topic to see every state’s bills on it.</p>
<div class="note small">A lean describes what legislators <em>proposed</em>, not the state’s politics, and it includes bills that died, so it reflects the whole session’s agenda. Faint cells rest on fewer than {MIN_FIRM} directional tags; “n/a” means fewer than {MIN_DIR}.</div>
<h2>Twenty issues compared</h2>
<p class="small muted">Chosen because most states have enough bills to compare and because together they span the major policy areas. The other 80 sub-topics are one click away below. Autonomous vehicles, a smaller category, has too few bills in any one state to show here; see its <a href="sub/{bs.slug("transportation.autonomous_vehicles")}.html">page</a>.</p>
<div class="scroll"><table class="heat"><thead><tr><th>Sub-topic</th>{head}</tr></thead><tbody>{"".join(srows)}</tbody></table></div>
<h2>Browse every sub-topic</h2>
{browse}
<details class="cat"><summary><div class="srow" style="grid-template-columns:1fr"><b>Broader view: the 16 parent topics</b></div></summary>
<p class="small muted">These averages pool many different sub-topics, so they hide a lot. Use them for orientation.</p>
<div class="scroll"><table class="heat"><thead><tr><th>Topic</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>
<h2>More ways to compare</h2>
<ul>
<li><a href="matches.html"><b>Matching bills</b></a>: near-identical bills filed in different states.</li>
<li><a href="timeline.html"><b>Timeline</b></a>: which state filed on a topic first, and when.</li>
<li><a href="enactment.html"><b>Enactment gap</b></a>: how much of what is proposed becomes law, and how the lean shifts.</li>
<li><a href="bipartisan.html"><b>Bipartisan</b></a>: where sponsors cross party lines.</li>
<li><a href="governors.html"><b>Governors</b></a>: vetoes and signing across states.</li>
<li><a href="pending.html"><b>Pending bills</b></a>: live bills in sessions that are still open.</li>
<li><a href="data.html"><b>Data</b></a>: download the tagged bills as CSV.</li></ul>"""
    (OUT / "index.html").write_text(cpage("Compare states", body, 1, "index.html"))


def page_topic(A, sub, top, tid):
    t = TOPICS[tid]
    rows, flat = [], []
    subs = sorted(t["subtopics"], key=lambda s: -sum(len(sub[(c, s["id"])]["bills"]) for c in STATE_ORDER))
    for s in subs:
        sid = s["id"]
        total = sum(len(sub[(c, sid)]["bills"]) for c in STATE_ORDER)
        if not total:
            continue
        counts = " · ".join(f'{c} {len(sub[(c, sid)]["bills"])}' for c in STATE_ORDER if sub[(c, sid)]["bills"])
        name = f'<a href="../sub/{bs.slug(sid)}.html"><b>{esc(bs.T(s["name"]))}</b></a>'
        if s["axis"] in ("A", "R"):
            dots = ""
            for i, c in enumerate(STATE_ORDER):
                d = sub[(c, sid)]["dir"]
                if len(d) >= MIN_DIR:
                    pos = (mean(d) + 2) / 4 * 100
                    dots += sdot(c, " faint" if len(d) < MIN_FIRM else "", f"left:{pos:.1f}%;top:{2 + (i % 2) * 28}px")
            note = f'<div class="muted small">{esc(bs.display_note(s["note"]))}</div>' if s.get("note") else ""
            rows.append(f'<div class="srow"><span>{name}{note}</span><div class="strip"><i class="mid"></i>{dots}</div><div class="cnt">{counts}</div></div>')
        else:
            flat.append(f'<tr><td>{name}</td><td>{esc(counts)}</td></tr>')
    body = f"""<p class="small"><a href="../index.html">← Compare states</a></p><h1>{esc(t["name"])}</h1>
<p class="lede">Sub-topics compared across states. A state’s marker is the average direction of its bills on that sub-topic; markers appear for states with at least {MIN_DIR} directional tags and are faint below {MIN_FIRM}.</p>
{legend()}{AXIS_C}
{"".join(rows) or '<p class="muted">No directional sub-topics here.</p>'}
{('<h2>Sub-topics without a direction</h2><table><thead><tr><th>Sub-topic</th><th>Bills by state</th></tr></thead><tbody>' + "".join(flat) + "</tbody></table>") if flat else ""}"""
    (OUT / "topic" / f"{tid}.html").write_text(cpage(t["name"], body, 2, "index.html"))


def bills_table(A, c, bills, depth, cap=150):
    order = {"Chaptered": 0, "Adopted": 1, "Vetoed": 2, "Passed": 3, "In Floor Process": 4, "In Committee Process": 5, "Pending Referral": 6}
    rows = []
    for b, t in sorted(bills, key=lambda x: (order.get(x[0]["status"], 7), x[0]["type"], str(x[0]["number"])))[:cap]:
        sm = f'<div class="muted small">{esc(b["summary"])}</div>' if b["summary"] else ""
        rows.append(f'<tr><td><a href="{bill_href(c, b, depth)}">{esc(b["key"])}</a></td><td>{esc(b["title"])}{sm}</td><td>{esc(bs.SL(b["status"]))}</td>'
                    f'<td>{esc(bs.DIR_WORD(t["direction"])) if t and t["lean"] is not None else ""}</td><td>{esc(b["intro"])}</td></tr>')
    more = f'<p class="muted small">Showing {cap} of {len(bills)}. Use the state’s <a href="{"../" * depth}{c.lower()}/bills.html">bill search</a> for the rest.</p>' if len(bills) > cap else ""
    return f'<table><thead><tr><th>Bill</th><th>Title</th><th>Status</th><th>Direction</th><th>Introduced</th></tr></thead><tbody>{"".join(rows)}</tbody></table>{more}'


def page_sub(A, sub, sid):
    s = SUB[sid]
    blocks = []
    for c in STATE_ORDER:
        d = sub[(c, sid)]
        if not d["bills"]:
            blocks.append(f'<div class="srow"><span>{sdot(c)} <b>{esc(state_name(c))}</b></span><span class="muted small">no bills on this sub-topic</span><span></span></div>')
            continue
        its = []
        for k in d["bills"]:
            b = A[c]["bills"][k]
            t = next(x for x in b["tags"] if x["subtopic"] == sid)
            its.append((b, t))
        if s["axis"] in ("A", "R"):
            m, _ = bs.meter(d["dir"], s["name"]) if d["dir"] else ('<span class="muted small">no directional tags</span>', None)
            mv = mean(d["dir"])
            chip = ""
            if mv is not None and len(d["dir"]) >= MIN_DIR:
                kind, word = ("rest", "Restrictive") if mv <= -bs.CUT else ("perm", "Permissive") if mv >= bs.CUT else ("mid", "Balanced")
                chip = f'<span class="chip {kind}">{word}</span> {fmt(mv)}'
        else:
            m, chip = '<span class="muted small">no direction scale</span>', ""
        laws = len(d["law"])
        row = (f'<div class="srow"><span>{sdot(c)} <b>{esc(state_name(c))}</b><br><span class="muted small">{len(d["bills"]):,} bills · {laws} became law</span></span>{m}<div class="cnt">{chip}</div></div>')
        blocks.append(f'<details class="cat"><summary>{row}</summary>{bills_table(A, c, its, 2)}</details>')
    note = f'<p class="small muted">{esc(bs.display_note(s["note"]))}</p>' if s.get("note") else ""
    body = f"""<p class="small"><a href="../topic/{s["topic_id"]}.html">← {esc(s["topic"])}</a></p><h1>{esc(bs.T(s["name"]))}</h1>{note}
<p class="small muted">Click a state to read its bills.</p>{AXIS_C if s["axis"] in ("A", "R") else ""}{"".join(blocks)}"""
    (OUT / "sub" / f"{bs.slug(sid)}.html").write_text(cpage(s["name"], body, 2, "index.html"))


# ------------------------------------------------------------------ 2. matching bills
def page_matches(A, sub, top):
    G = cm.find_matches(A, min_sim=0.45)
    cards = []
    for g in G[:500]:
        mem = [(c, A[c]["bills"][k]) for c, k in g["members"]]
        tcount = Counter(t for c, b in mem for t in b["topics"])
        topics = [t for t, _ in tcount.most_common(3)]
        law = sorted({c for c, b in mem if b["status"] == "Chaptered"})
        pend = sorted({c for c, b in mem if c in cd.OPEN_SESSIONS and b["status"] in cd.ACTIVE})
        strong = g["sim"] >= 0.56
        if law:
            outcome = f'Became law in {", ".join(law)}'
            rest = [c for c in g["states"] if c not in law]
            if rest:
                outcome += f'; did not become law in {", ".join(rest)}'
        else:
            outcome = "Did not become law in any of these states" + (f' (still pending in {", ".join(pend)})' if pend else "")
        rows = []
        for c, b in sorted(mem, key=lambda x: STATE_ORDER.index(x[0])):
            t = next((x for x in b["tags"] if x["topic"] and SUB[x["subtopic"]]["topic_id"] in topics), b["tags"][0])
            d = esc(bs.DIR_WORD(t["direction"])) if t["lean"] is not None else ""
            rows.append(f'<tr><td>{sdot(c)}</td><td><a href="../{c.lower()}/bill/{b["slug"]}.html">{esc(b["key"])}</a> · {esc(b["title"])}<div class="muted small">{esc(b["summary"])}</div></td>'
                        f'<td>{esc(bs.SL(b["status"]))}</td><td>{d}</td></tr>')
        chips = "".join(f'<span class="chip">{esc(TOPICS[t]["name"])}</span>' for t in topics)
        cards.append(f'<div class="mcard" data-t="{" ".join(topics)}" data-tier="{"strong" if strong else "related"}" data-law="{1 if law else 0}">'
                     f'<div class="mhead"><span class="chip {"tag-strong" if strong else "tag-related"}">{"Strong match" if strong else "Related"}</span>{chips}<span class="small muted">{esc(outcome)}</span></div>'
                     f'<table><tbody>{"".join(rows)}</tbody></table></div>')
    opts = "".join(f'<option value="{t}">{esc(TOPICS[t]["name"])}</option>' for t in POLICY_TOPICS)
    js = """const cards=[...document.querySelectorAll('.mcard')],tp=document.getElementById('mt'),ti=document.getElementById('mtier'),lw=document.getElementById('mlaw'),ct=document.getElementById('mcount');
function run(){let n=0;cards.forEach(c=>{const ok=(!tp.value||c.dataset.t.split(' ').includes(tp.value))&&(ti.value===''||c.dataset.tier===ti.value)&&(!lw.checked||c.dataset.law==='1');c.style.display=ok?'':'none';if(ok)n++});ct.textContent=n+' groups'}
[tp,ti,lw].forEach(e=>e.addEventListener('input',run));run();"""
    body = f"""<h1>Matching bills</h1>
<p class="lede">The same idea, filed in more than one state: model legislation, copycat bills and parallel efforts. Bills are grouped by how closely their titles and plain-language summaries match.</p>
<div class="note small"><b>Strong match</b> means the summaries read nearly the same. <b>Related</b> means they cover the same specific idea but may differ in detail, so check the text. Matching uses the model-written summaries, so thin summaries can miss matches. Generic budget and ceremonial bills are left out.</div>
<div class="fbar"><label>Topic <select id="mt"><option value="">All topics</option>{opts}</select></label><label>Match <select id="mtier"><option value="">Strong and related</option><option value="strong">Strong only</option></select></label><label><input type="checkbox" id="mlaw"> Became law somewhere</label><span class="muted small" id="mcount"></span></div>
{"".join(cards)}<script>{js}</script>"""
    (OUT / "matches.html").write_text(cpage("Matching bills", body, 1, "matches.html"))
    print("match groups:", len(G))


# ------------------------------------------------------------------ 3. timeline
def month_list(lo, hi):
    y, m = int(lo[:4]), int(lo[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= hi:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def page_timeline(A, sub, top):
    dates = [b["intro"][:7] for S in A.values() for b in S["bills"].values() if b["intro"] and b["tags"]]
    months = month_list(max(min(dates), "2024-11"), max(dates))
    mi = {m: i for i, m in enumerate(months)}
    keys = ["all"] + POLICY_TOPICS + [s for s in SUB if SUB[s]["topic_id"] not in cd.EXCLUDED]
    counts = {k: {c: [0] * len(months) for c in STATE_ORDER} for k in keys}
    dts = {k: {c: [] for c in STATE_ORDER} for k in keys}
    for c, S in A.items():
        for b in S["bills"].values():
            if not b["intro"] or not b["tags"] or b["intro"][:7] not in mi:
                continue
            ks = {"all"} | set(b["topics"]) | {t["subtopic"] for t in b["tags"]}
            for k in ks:
                counts[k][c][mi[b["intro"][:7]]] += 1
                dts[k][c].append(b["intro"])
    first = {}
    for k in keys:
        first[k] = {}
        for c in STATE_ORDER:
            d = sorted(dts[k][c])
            first[k][c] = [d[0] if d else "", d[9] if len(d) >= 10 else ""]
    # static table: when each state reached its 10th bill on a topic
    rows = []
    for tid in POLICY_TOPICS:
        tenth = {c: first[tid][c][1] for c in STATE_ORDER}
        valid = [v for v in tenth.values() if v]
        lo = min(valid) if valid else ""
        cells = "".join(f'<td class="{"" if tenth[c] else "na"}">{("<b>" if tenth[c] == lo else "") + esc(tenth[c] or "—") + ("</b>" if tenth[c] == lo else "")}<span class="n">first {esc(first[tid][c][0] or "—")}</span></td>' for c in STATE_ORDER)
        rows.append(f'<tr><td class="rowh">{esc(TOPICS[tid]["name"])}</td>{cells}</tr>')
    head = "".join(f'<th>{sdot(c)}<br>{esc(state_name(c))}</th>' for c in STATE_ORDER)
    groups = "".join(f'<optgroup label="{esc(TOPICS[t]["name"])}"><option value="{t}">All of {esc(TOPICS[t]["name"])}</option>' + "".join(f'<option value="{s["id"]}">{esc(bs.T(s["name"]))}</option>' for s in TOPICS[t]["subtopics"]) + "</optgroup>" for t in POLICY_TOPICS)
    data = json.dumps({"months": months, "colors": STATE_COLOR, "names": {c: state_name(c) for c in STATE_ORDER}, "counts": counts, "first": first}, separators=(",", ":"))
    js = """const D=__D__;const sel=document.getElementById('tk'),same=document.getElementById('same'),box=document.getElementById('tl');
function draw(){const k=sel.value,M=D.months,W=900,H=64,bw=W/M.length;let gmax=1;for(const c in D.names)gmax=Math.max(gmax,...D.counts[k][c]);
let out='';for(const c in D.names){const v=D.counts[k][c],tot=v.reduce((a,b)=>a+b,0),mx=same.checked?gmax:Math.max(1,...v);let s='<svg viewBox="0 0 '+W+' '+(H+16)+'" role="img" aria-label="'+D.names[c]+' bills filed per month">';
for(let i=0;i<M.length;i++){const h=Math.round(v[i]/mx*H);if(h)s+='<rect x="'+(i*bw+1)+'" y="'+(H-h)+'" width="'+(bw-2)+'" height="'+h+'" fill="'+D.colors[c]+'"><title>'+M[i]+': '+v[i]+'</title></rect>';
if(M[i].slice(5)==='01'||i===0)s+='<text x="'+(i*bw)+'" y="'+(H+13)+'" font-size="11" fill="#5b6577">'+(M[i].slice(5)==='01'?M[i].slice(0,4):M[i])+'</text>'}
s+='<line x1="0" x2="'+W+'" y1="'+H+'" y2="'+H+'" stroke="#c8ced9"/></svg>';
const f=D.first[k][c],pk=v.indexOf(Math.max(...v));
out+='<div class="tl-row"><div><span class="sdot" style="background:'+D.colors[c]+'">'+c+'</span> <b>'+D.names[c]+'</b><div class="tl-meta">'+tot+' bills'+(tot?'<br>first '+f[0]+(f[1]?'<br>10th '+f[1]:'')+'<br>peak '+M[pk]+' ('+v[pk]+')':'')+'</div></div><div>'+s+'</div></div>'}
box.innerHTML=out}
[sel,same].forEach(e=>e.addEventListener('input',draw));draw();""".replace("__D__", data)
    body = f"""<h1>Timeline</h1>
<p class="lede">When each state filed bills on a topic. Pick a topic or a single sub-topic to see bills introduced per month, and when each state filed its first and tenth bill on it.</p>
<div class="note small">Legislative calendars differ: Florida and Washington meet in a short winter-spring window, California and Massachusetts file all year, and some states allow pre-filing. A later start can reflect the calendar, not a lack of interest.</div>
<div class="fbar"><label>Topic <select id="tk"><option value="all">All policy topics</option>{groups}</select></label><label><input type="checkbox" id="same"> Same scale for every state</label></div>
<div id="tl"></div>
<h2>Who filed first, by topic</h2>
<p class="small muted">Date of each state’s tenth bill on the topic (bold = earliest), with the first bill below. The tenth bill is steadier than the first, which can be a single early filing.</p>
<div class="scroll"><table class="heat"><thead><tr><th>Topic</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<script>{js}</script>"""
    (OUT / "timeline.html").write_text(cpage("Timeline", body, 1, "timeline.html"))


# ------------------------------------------------------------------ 4. enactment gap
def enact_cells(buckets, bills_n):
    out = []
    for c in STATE_ORDER:
        d = buckets[c]
        n = len(d["bills"])
        if not n:
            out.append('<td class="na">—</td>')
            continue
        rate = len(d["law"]) / n
        ma, ml = mean(d["dir"]), mean(d["law_dir"])
        shift = f'{fmt(ma)} → {fmt(ml)}' if len(d["dir"]) >= MIN_DIR and len(d["law_dir"]) >= MIN_DIR else "no lean shown"
        cls = "faint" if n < 10 or c in cd.OPEN_SESSIONS else ""
        out.append(f'<td class="{cls}" style="{seq_style(rate)}"><b>{rate * 100:.0f}%</b><span class="n">{n:,} bills · {shift}</span></td>')
    return "".join(out)


def page_enactment(A, sub, top):
    head = "".join(f'<th>{sdot(c)}<br>{esc(state_name(c))}{"<br><span class=muted>session open</span>" if c in cd.OPEN_SESSIONS else ""}</th>' for c in STATE_ORDER)
    blocks = []
    for tid in POLICY_TOPICS:
        trow = f'<tr><td class="rowh"><b style="display:inline;font-family:inherit;font-size:16px">{esc(TOPICS[tid]["name"])}</b></td>{enact_cells({c: top[(c, tid)] for c in STATE_ORDER}, None)}</tr>'
        srows = "".join(f'<tr><td class="rowh">{esc(bs.T(sb["name"]))}</td>{enact_cells({c: sub[(c, sb["id"])] for c in STATE_ORDER}, None)}</tr>' for sb in sorted(TOPICS[tid]["subtopics"], key=lambda x: -sum(len(sub[(c, x["id"])]["bills"]) for c in STATE_ORDER)) if any(sub[(c, sb["id"])]["bills"] for c in STATE_ORDER))
        blocks.append((trow, srows, tid))
    main_rows = "".join(f'<tr><td class="rowh"><a href="#t-{tid}"><b style="display:inline;font-family:inherit;font-size:16px">{esc(TOPICS[tid]["name"])}</b></a></td>{enact_cells({c: top[(c, tid)] for c in STATE_ORDER}, None)}</tr>' for _, _, tid in blocks)
    details = "".join(f'<details class="cat" id="t-{tid}"><summary><div class="srow" style="grid-template-columns:1fr"><b>{esc(TOPICS[tid]["name"])}: sub-topics</b></div></summary><div class="scroll"><table class="heat"><thead><tr><th>Sub-topic</th>{head}</tr></thead><tbody>{srows}</tbody></table></div></details>' for _, srows, tid in blocks)
    body = f"""<h1>Enactment gap</h1>
<p class="lede">How much of what gets proposed becomes law. Each cell shows the share of a state’s bills on the topic that became law, with the average direction of all its bills on the topic, then of the ones that became law (−2 Restrictive to +2 Permissive).</p>
<div class="note small">Massachusetts and DC are still in session, so their numbers show progress so far, not outcomes (shaded lighter). Other states’ sessions are over, so every bill that did not pass counts as not enacted. States differ a lot in how many bills they file and in how committees work, so compare the lean shift more than the raw rate.</div>
<h2>By topic</h2>
<div class="scroll"><table class="heat"><thead><tr><th>Topic</th>{head}</tr></thead><tbody>{main_rows}</tbody></table></div>
<h2>Down to sub-topics</h2><p class="small muted">Open a topic.</p>{details}"""
    (OUT / "enactment.html").write_text(cpage("Enactment gap", body, 1, "enactment.html"))


# ------------------------------------------------------------------ 6. bipartisan
def page_bipartisan(A, sub, top):
    def stats(c, bills):
        den = [b for b in bills if b["parties"]]
        bip = [b for b in den if {"DEM", "REP"} <= b["parties"]]
        law = [b for b in den if b["status"] == "Chaptered"]
        lawb = [b for b in law if {"DEM", "REP"} <= b["parties"]]
        return len(den), len(bip), len(law), len(lawb)
    has_rep = {c: any(L.get("party") == "REP" and L.get("active", True) for L in A[c]["legs"].values()) for c in STATE_ORDER}
    head = "".join(f'<th>{sdot(c)}<br>{esc(state_name(c))}</th>' for c in STATE_ORDER)

    def cells(getter):
        out = []
        for c in STATE_ORDER:
            bills = getter(c)
            if not has_rep[c]:
                out.append('<td class="na">no Republican members</td>')
                continue
            den, bip, law, lawb = stats(c, bills)
            if den < 5:
                out.append(f'<td class="na">—<span class="n">{den} bills</span></td>')
                continue
            lawtxt = f"laws {lawb / law * 100:.0f}% of {law}" if law >= 5 else "few laws"
            out.append(f'<td style="{seq_style(bip / den)}"><b>{bip / den * 100:.0f}%</b><span class="n">of {den:,} · {lawtxt}</span></td>')
        return "".join(out)
    tb = {}
    for c in STATE_ORDER:
        for k, b in A[c]["bills"].items():
            for t in b["tags"]:
                tb.setdefault((c, SUB[t["subtopic"]]["topic_id"]), {})[k] = b
                tb.setdefault((c, t["subtopic"]), {})[k] = b
    rows = "".join(f'<tr><td class="rowh"><a href="#t-{tid}"><b style="display:inline;font-family:inherit;font-size:16px">{esc(TOPICS[tid]["name"])}</b></a></td>{cells(lambda c, tid=tid: list(tb.get((c, tid), {}).values()))}</tr>' for tid in POLICY_TOPICS)
    details = []
    for tid in POLICY_TOPICS:
        srows = "".join(f'<tr><td class="rowh">{esc(bs.T(sb["name"]))}</td>{cells(lambda c, sid=sb["id"]: list(tb.get((c, sid), {}).values()))}</tr>' for sb in TOPICS[tid]["subtopics"] if any(tb.get((c, sb["id"])) for c in STATE_ORDER))
        cand = []
        for c in STATE_ORDER:
            for b in tb.get((c, tid), {}).values():
                if b["status"] == "Chaptered" and {"DEM", "REP"} <= b["parties"]:
                    cand.append((b["n_authors"], c, b))
        cand.sort(key=lambda x: -x[0])
        lis = "".join(f'<tr><td>{sdot(c)}</td><td><a href="../{c.lower()}/bill/{b["slug"]}.html">{esc(b["key"])}</a> · {esc(b["title"])}<div class="muted small">{esc(b["summary"])}</div></td><td class="n">{n} sponsors</td></tr>' for n, c, b in cand[:8])
        lst = f'<h3>Bipartisan bills on this topic that became law (most sponsors first)</h3><table><tbody>{lis}</tbody></table>' if lis else ""
        details.append(f'<details class="cat" id="t-{tid}"><summary><div class="srow" style="grid-template-columns:1fr"><b>{esc(TOPICS[tid]["name"])}: sub-topics and bills</b></div></summary><div class="scroll"><table class="heat"><thead><tr><th>Sub-topic</th>{head}</tr></thead><tbody>{srows}</tbody></table></div>{lst}</details>')
    body = f"""<h1>Bipartisan</h1>
<p class="lede">Where sponsors cross party lines. A bill counts as bipartisan when its listed sponsors include at least one Democrat and one Republican. Each cell shows the share of a state’s bills on the topic that are bipartisan, how many bills that is out of, and the same share among bills that became law.</p>
<div class="note small">States list sponsors differently: Massachusetts bills often carry many co-sponsors, while a bill in another state may name only a few, so compare patterns across topics within a state before comparing states. Only bills with at least one individual legislator sponsor count; committee bills are left out. Independents don’t count toward either side. DC’s Council has no Republican members.</div>
<h2>By topic</h2><div class="scroll"><table class="heat"><thead><tr><th>Topic</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>
<h2>Down to sub-topics</h2><p class="small muted">Open a topic.</p>{"".join(details)}"""
    (OUT / "bipartisan.html").write_text(cpage("Bipartisan", body, 1, "bipartisan.html"))


# ------------------------------------------------------------------ 7. governors
EXEC_NAME = {"CA": "Governor", "FL": "Governor", "MA": "Governor", "OR": "Governor", "WA": "Governor", "DC": "Mayor"}


def page_governors(A, sub, top):
    rows, grid = [], {}
    for c in STATE_ORDER:
        bills = A[c]["bills"].values()
        sig = [b for b in bills if b["status"] == "Chaptered"]
        vet = [b for b in bills if b["status"] == "Vetoed"]
        reached = len(sig) + len(vet)
        rate = f"{len(vet) / reached * 100:.1f}%" if reached else "—"
        ls = mean([t["lean"] for b in sig for t in b["tags"] if t["lean"] is not None])
        lv = mean([t["lean"] for b in vet for t in b["tags"] if t["lean"] is not None])
        nv = len([1 for b in vet for t in b["tags"] if t["lean"] is not None])
        shown = f'{fmt(ls)} signed · {fmt(lv)} vetoed' if nv >= 10 else "too few vetoes to compare"
        note = {"MA": "Line-item vetoes on budget bills are not counted as vetoes here.", "DC": "No mayoral vetoes appear in the Council’s records for this period.",
                "WA": "Partial vetoes of signed bills are not counted.", "OR": "", "FL": "Line-item budget vetoes are not counted.", "CA": ""}.get(c, "")
        link = f'<a href="../{c.lower()}/vetoes.html">Open</a>' if vet else ""
        rows.append(f'<tr><td>{sdot(c)} <b>{esc(state_name(c))}</b></td><td>{EXEC_NAME[c]}</td><td class="n">{reached:,}</td><td class="n">{len(sig):,}</td><td class="n">{len(vet):,}</td><td class="n">{rate}</td><td>{shown}</td><td>{link}</td><td class="small muted">{esc(note)}</td></tr>')
        for tid in POLICY_TOPICS:
            r = sum(1 for b in sig + vet if tid in b["topics"])
            v = sum(1 for b in vet if tid in b["topics"])
            grid[(c, tid)] = (r, v)
    show = [c for c in STATE_ORDER if sum(v for (cc, _), (r, v) in grid.items() if cc == c) >= 5]
    head = "".join(f'<th>{sdot(c)}<br>{esc(state_name(c))}</th>' for c in show)
    trows = []
    for tid in POLICY_TOPICS:
        cells = []
        for c in show:
            r, v = grid[(c, tid)]
            cells.append(f'<td class="na">—<span class="n">{r} bills</span></td>' if r < 8 else f'<td style="{seq_style(min(1, v / r * 4))}"><b>{v / r * 100:.0f}%</b><span class="n">{v} of {r}</span></td>')
        trows.append(f'<tr><td class="rowh">{esc(TOPICS[tid]["name"])}</td>{"".join(cells)}</tr>')
    body = f"""<h1>Governors</h1>
<p class="lede">How chief executives treat the bills that reach them. A bill “reaches” the governor once it passes the legislature: it either became law or was vetoed.</p>
<div class="scroll"><table><thead><tr><th>State</th><th>Executive</th><th class="n">Reached</th><th class="n">Became law</th><th class="n">Vetoed</th><th class="n">Veto rate</th><th>Average direction</th><th>Details</th><th>Notes</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<div class="note small">Veto practices differ: California’s governor must act on a large volume in a short window, and some states’ governors have line-item vetoes that are not counted here. States with fewer than 5 full vetoes are left out of the topic grid.</div>
<h2>Veto rate by topic</h2><p class="small muted">Share of bills reaching the executive that were vetoed, for topics with at least 8 such bills. Darker means a higher rate.</p>
<div class="scroll"><table class="heat"><thead><tr><th>Topic</th>{head}</tr></thead><tbody>{"".join(trows)}</tbody></table></div>"""
    (OUT / "governors.html").write_text(cpage("Governors", body, 1, "governors.html"))


# ------------------------------------------------------------------ 8. pending bills
def page_pending(A, sub, top):
    rows = []
    for c in STATE_ORDER:
        if c not in cd.OPEN_SESSIONS:
            continue
        for k, b in A[c]["bills"].items():
            if b["status"] in cd.ACTIVE and not b["ceremonial"]:
                rows.append({"s": c, "k": k, "t": b["title"], "st": bs.SL(b["status"]), "l": b["last"], "i": b["intro"], "tp": b["topics"], "sm": b["summary"], "au": b["lead"], "h": f'../{c.lower()}/bill/{b["slug"]}.html'})
    from datetime import date
    asof = date.today().isoformat()
    data = json.dumps({"rows": rows, "asof": asof, "topics": {t: TOPICS[t]["name"] for t in POLICY_TOPICS}, "names": {c: state_name(c) for c in cd.OPEN_SESSIONS if c in A}, "colors": STATE_COLOR}, separators=(",", ":"), ensure_ascii=False)
    js = """const D=__D__;const R=D.rows;const $=id=>document.getElementById(id);
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
const asof=new Date(D.asof+'T00:00:00Z');let shown=100,view=[];
function idle(r){return r.l?Math.max(0,Math.round((asof-new Date(r.l+'T00:00:00Z'))/864e5)):null}
function run(){const q=$('pq').value.toLowerCase().trim().split(/\\s+/).filter(Boolean),st=$('ps').value,tp=$('pt').value,ss=$('pstat').value,id=parseInt($('pidle').value||'0',10);
view=R.filter(r=>(!st||r.s===st)&&(!tp||r.tp.includes(tp))&&(!ss||r.st===ss)&&(!id||(idle(r)!==null&&idle(r)>=id))&&q.every(w=>(r.k+' '+r.t+' '+r.sm+' '+r.au).toLowerCase().includes(w)));
view.sort((a,b)=>(b.l||'').localeCompare(a.l||''));render()}
function render(){const v=view.slice(0,shown);$('pcount').textContent=view.length.toLocaleString()+' pending bills';
$('pout').innerHTML=v.map(r=>'<tr><td><span class="sdot" style="background:'+D.colors[r.s]+'">'+r.s+'</span></td><td><a href="'+r.h+'">'+esc(r.k)+'</a> · '+esc(r.t)+(r.sm?'<div class="muted small">'+esc(r.sm)+'</div>':'')+'<div class="muted small">'+[r.au?'Lead author: '+esc(r.au):'',r.tp.map(t=>esc(D.topics[t])).join(', ')].filter(Boolean).join(' · ')+'</div></td><td>'+esc(r.st)+'</td><td>'+esc(r.l||'')+'<div class="muted small">'+(idle(r)!==null?idle(r)+' days idle':'')+'</div></td></tr>').join('');
$('pmore').style.display=view.length>shown?'':'none'}
$('pmore').onclick=()=>{shown+=200;render()};
['pq','ps','pt','pstat','pidle'].forEach(i=>$(i).addEventListener('input',()=>{shown=100;run()}));run();""".replace("__D__", data)
    topts = "".join(f'<option value="{t}">{esc(TOPICS[t]["name"])}</option>' for t in POLICY_TOPICS)
    sopts = "".join(f'<option value="{c}">{esc(state_name(c))}</option>' for c in cd.OPEN_SESSIONS if c in A)
    body = f"""<h1>Pending bills</h1>
<p class="lede">Live bills in the states whose sessions are still open: Massachusetts (the 194th General Court runs through January 2027) and the DC Council (Council Period 26 runs through 2026). In every other state the session is over, so a bill that did not pass has died.</p>
<div class="note small">Bills are sorted by most recent action. “Days idle” counts back from {esc(asof)}; a last action dated later than that is a scheduled step. A long idle spell in a committee usually means a bill is stalled, but Massachusetts bills can be revived. Ceremonial measures are left out.</div>
<div class="fbar"><input id="pq" placeholder="Search bill number, title, summary or author" aria-label="Search" style="min-width:280px"><label>State <select id="ps"><option value="">Both</option>{sopts}</select></label><label>Topic <select id="pt"><option value="">All topics</option>{topts}</select></label>
<label>Status <select id="pstat"><option value="">Any</option><option>In Committee Process</option><option>In Floor Process</option><option>Passed</option><option>Pending Referral</option></select></label>
<label>Idle <select id="pidle"><option value="">Any</option><option value="90">90+ days</option><option value="180">180+ days</option><option value="365">1+ year</option></select></label><span class="muted small" id="pcount"></span></div>
<div class="scroll"><table><thead><tr><th></th><th>Bill</th><th>Status</th><th>Last action</th></tr></thead><tbody id="pout"></tbody></table></div>
<p><button id="pmore" style="font:inherit;padding:7px 16px;border-radius:8px;border:1px solid var(--axis);background:#fff;cursor:pointer">Show more</button></p>
<script>{js}</script>"""
    (OUT / "pending.html").write_text(cpage("Pending bills", body, 1, "pending.html"))


# ------------------------------------------------------------------ 9. data downloads
def page_data(A, sub, top):
    def dword(d):
        return bs.DIR_WORD(d)
    with open(DATA_OUT / "statetrack_bills.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["state", "bill", "title", "status", "introduced", "last_action", "lead_author", "topics", "summary", "official_url", "statetrack_page"])
        for c in STATE_ORDER:
            for k, b in A[c]["bills"].items():
                w.writerow([c, k, b["title"], bs.SL(b["status"]), b["intro"], b["last"], b["lead"], "; ".join(TOPICS[t]["name"] for t in b["topics"]), b["summary"], b["url"],
                            f"https://mraifman.github.io/statetrack/{c.lower()}/bill/{b['slug']}.html"])
    with open(DATA_OUT / "statetrack_tags.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["state", "bill", "topic", "sub_topic", "direction", "score", "mechanism", "funding", "confidence"])
        for c in STATE_ORDER:
            for k, b in A[c]["bills"].items():
                for t in b["tags"]:
                    w.writerow([c, k, SUB[t["subtopic"]]["topic"], bs.T(SUB[t["subtopic"]]["name"]), dword(t["direction"]) if t["lean"] is not None else "", "" if t["lean"] is None else t["lean"],
                                t.get("mechanism", ""), t.get("funding", ""), t.get("confidence", "")])
    with open(DATA_OUT / "statetrack_legislators.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["state", "name", "party", "chamber", "district", "active", "bills_authored_or_coauthored"])
        for c in STATE_ORDER:
            for lid, L in A[c]["legs"].items():
                w.writerow([c, L["name"], L.get("party", ""), L["house"], L.get("district", ""), "yes" if L.get("active", True) else "no", A[c]["authored"].get(lid, 0)])
    with open(DATA_OUT / "statetrack_topic_matrix.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["state", "topic", "sub_topic", "bills", "directional_tags", "mean_direction", "became_law"])
        for c in STATE_ORDER:
            for sid in SUB:
                if SUB[sid]["topic_id"] in cd.EXCLUDED:
                    continue
                d = sub[(c, sid)]
                if d["bills"]:
                    w.writerow([c, SUB[sid]["topic"], bs.T(SUB[sid]["name"]), len(d["bills"]), len(d["dir"]), "" if not d["dir"] else f"{mean(d['dir']):.3f}", len(d["law"])])
    sizes = {f.name: f.stat().st_size / 1e6 for f in DATA_OUT.glob("statetrack_*.csv")}
    items = [("statetrack_bills.csv", "One row per bill: state, bill, title, status, dates, lead author, topics, plain-language summary and links."),
             ("statetrack_tags.csv", "One row per tag: the topic and sub-topic the model assigned to a bill, its direction against current law (and −2 to +2 score), mechanism, funding effect and confidence."),
             ("statetrack_legislators.csv", "One row per legislator: party, chamber, district and bills authored or co-authored."),
             ("statetrack_topic_matrix.csv", "The numbers behind the comparison pages: bills, directional tags, mean direction and bills that became law, per state and sub-topic.")]
    lis = "".join(f'<li><a href="../data/{n}" download><b>{n}</b></a> ({sizes.get(n, 0):.1f} MB)<br><span class="small muted">{esc(d)}</span></li>' for n, d in items)
    body = f"""<h1>Data</h1>
<p class="lede">Download the tagged bills for all {len(STATE_ORDER)} states as plain CSV files that open in Excel, Sheets, R or Python.</p>
<ul>{lis}</ul>
<h2>Reading the columns</h2>
<ul><li><b>direction</b>: how the bill changes current law on a sub-topic. Restrictive moves toward less permission or more rules; Permissive toward more permission, access or fewer rules; Mixed, Neutral and Unclear are left out of averages. The <b>score</b> runs −2 (Strongly Restrictive) to +2 (Strongly Permissive).</li>
<li><b>status</b>: Became Law, Vetoed, Passed (awaiting the executive), In Committee Process, In Floor Process, Pending Referral, Died, Failed Passage in Committee. DC resolutions that were adopted show as Adopted.</li>
<li>Labels are written by an AI model from each bill’s title and official summary. They are approximate; the quoted evidence for each call is on the bill’s page.</li>
<li>State session calendars differ, and Massachusetts and DC are still in session, so “Died” is not the same thing everywhere.</li></ul>
"""
    (OUT / "data.html").write_text(cpage("Data", body, 1, "data.html"))


STATE_ORDER = []
HUB_SUB = {}


def main():
    global STATE_ORDER
    A = cd.load_all()
    STATE_ORDER = list(A)
    for d in ("topic", "sub"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "compare.css").write_text(CCSS)
    sub, top = collect(A)
    global HUB_SUB
    HUB_SUB = sub
    page_hub(A, top)
    for tid in POLICY_TOPICS:
        page_topic(A, sub, top, tid)
    for sid in SUB:
        if SUB[sid]["topic_id"] in cd.EXCLUDED:
            continue
        page_sub(A, sub, sid)
    for name in ("matches", "timeline", "enactment", "bipartisan", "governors", "pending", "data"):
        fn = globals().get("page_" + name)
        if fn:
            fn(A, sub, top)
    print("compare pages written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
