#!/usr/bin/env python3
"""Build the StateTrack California demo as a static site in docs/.

Inputs (data/ca/): bills.json, legislators.json, votes.json.gz, history.json.gz, tags.json; taxonomy/taxonomy.json.
Pages: overview, topics, all-bills search, bills, legislators, method. No dependencies beyond the standard library.
Legislator profiles are counts of what each legislator authored and how they voted, by sub-topic and direction, with
the bills behind every count. No score or label is computed from them.
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
esc = html.escape

REST = {"restricts", "strongly_restricts", "tightens", "strongly_tightens"}
PERM = {"expands", "strongly_expands", "loosens", "strongly_loosens"}


def group(direction: str) -> str:
    if direction in ("strongly_restricts", "strongly_tightens"):
        return "rest2"
    if direction in ("restricts", "tightens"):
        return "rest1"
    if direction == "mixed":
        return "mixed"
    if direction == "neutral":
        return "neutral"
    if direction in ("expands", "loosens"):
        return "perm1"
    if direction in ("strongly_expands", "strongly_loosens"):
        return "perm2"
    return "other"


GROUP_LABEL = {"rest2": "Strongly restricts / tightens", "rest1": "Restricts / tightens", "mixed": "Mixed", "neutral": "Neutral",
               "perm1": "Expands / loosens", "perm2": "Strongly expands / loosens"}
ORDER = ["rest2", "rest1", "mixed", "neutral", "perm1", "perm2"]
DIR_WORD = lambda d: d.replace("_", " ")

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
main{padding:24px 0 64px}h1{font-size:30px;line-height:1.2;margin:8px 0 6px}h2{font-size:20px;margin:32px 0 8px}h3{font-size:16px;margin:20px 0 6px}
.lede{color:var(--ink2);max-width:70ch;margin:0 0 16px}.muted{color:var(--muted)}.small{font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.tile b{display:block;font-size:28px;line-height:1.1}.tile span{color:var(--ink2);font-size:13px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--ink2);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.bars .row{display:grid;grid-template-columns:minmax(120px,230px) 1fr 56px;gap:10px;align-items:center;padding:3px 0}
.bars .track{height:16px}.bars .fill{height:100%;background:var(--accent);border-radius:0 4px 4px 0;min-width:2px}
.bars a{color:var(--ink);text-decoration:none}.bars a:hover{text-decoration:underline}.bars .v{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
.div{display:flex;height:16px;gap:2px;border-radius:4px;overflow:hidden;background:transparent}.div i{display:block;height:100%;min-width:2px}
.div .rest2{background:var(--rest2)}.div .rest1{background:var(--rest1)}.div .mixed{background:var(--mixed)}.div .neutral{background:var(--neutral)}.div .perm1{background:var(--perm1)}.div .perm2{background:var(--perm2)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin:8px 0;font-size:13px;color:var(--ink2)}.legend span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px;background:var(--c)}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 9px;font-size:12px;color:var(--ink2);margin:1px 4px 1px 0;white-space:nowrap}
.dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:0}
.party{font-weight:600}.DEM{color:#2a78d6}.REP{color:#d03b3b}
blockquote{margin:6px 0;padding:6px 12px;border-left:3px solid var(--axis);color:var(--ink2);background:var(--surface)}
input,select{font:inherit;padding:7px 9px;border:1px solid var(--axis);border-radius:8px;background:var(--surface);color:var(--ink)}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.filters input{flex:1;min-width:200px}
details summary{cursor:pointer;color:var(--ink2)}footer{color:var(--muted);font-size:13px;padding:24px 0;border-top:1px solid var(--line)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}.note{border-left:3px solid var(--accent);padding:6px 12px;background:var(--surface)}
@media (max-width:640px){.bars .row{grid-template-columns:1fr 60px}.bars .track{grid-column:1/-1;order:3}}
"""


def page(title, body, depth=0, desc=""):
    base = "../" * depth
    body = body.replace("<table", '<div class="scroll"><table').replace("</table>", "</table></div>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · StateTrack</title><meta name="description" content="{esc(desc or title)}"><style>{CSS}</style></head><body>
<header class="site"><div class="wrap"><nav><a class="brand" href="{base}index.html">StateTrack</a><a href="{base}index.html">Overview</a><a href="{base}bills.html">All bills</a>
<a href="{base}legislators.html">Legislators</a><a href="{base}method.html">How it works</a><span class="muted small">California 2025–26 · demo</span></nav></div></header>
<main><div class="wrap">{body}</div></main><footer><div class="wrap">Demo for California’s 2025–26 session. Bill data: California Legislative Information (official bulk file). Topics and directions are labelled by an AI model from the bill’s title and the Legislative Counsel’s digest, and are approximate. <a href="{base}method.html">How it works</a></div></footer></body></html>"""


def legend():
    colors = {"rest2": "var(--rest2)", "rest1": "var(--rest1)", "mixed": "var(--mixed)", "neutral": "var(--neutral)", "perm1": "var(--perm1)", "perm2": "var(--perm2)"}
    return '<div class="legend">' + "".join(f'<span style="--c:{colors[g]}">{GROUP_LABEL[g]}</span>' for g in ORDER) + "</div>"


def divbar(counts):
    total = sum(counts.get(g, 0) for g in ORDER)
    if not total:
        return '<span class="muted small">no directional tags</span>'
    segs = "".join(f'<i class="{g}" style="flex:{counts[g]}" title="{GROUP_LABEL[g]}: {counts[g]}"></i>' for g in ORDER if counts.get(g))
    return f'<div class="div" role="img" aria-label="Direction split: ' + ", ".join(f"{GROUP_LABEL[g]} {counts[g]}" for g in ORDER if counts.get(g)) + f'">{segs}</div>'


def slug(key):
    return re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")


def main():
    bills = json.loads((DATA / "bills.json").read_text())
    legislators = json.loads((DATA / "legislators.json").read_text())
    votes = json.load(gzip.open(DATA / "votes.json.gz", "rt"))
    history = json.load(gzip.open(DATA / "history.json.gz", "rt"))
    tagged = json.loads((DATA / "tags.json").read_text())["bills"]
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "bill").mkdir(parents=True)
    (OUT / "topic").mkdir()
    (OUT / "legislator").mkdir()
    (OUT / ".nojekyll").write_text("")

    # per-bill tag view
    btags = {k: [t for t in v.get("tags", []) if t["subtopic"] in SUB] for k, v in tagged.items()}
    topic_bills = defaultdict(set)
    sub_bills = defaultdict(list)
    sub_dir = defaultdict(Counter)
    for k, tags in btags.items():
        for t in tags:
            s = SUB[t["subtopic"]]
            topic_bills[s["topic_id"]].add(k)
            sub_bills[t["subtopic"]].append(k)
            if SUB[t["subtopic"]]["axis"] in ("A", "R"):
                sub_dir[t["subtopic"]][group(t["direction"])] += 1
    n_tagged = sum(1 for k in btags if btags[k])

    # legislator profiles
    lid_slug = {lid: slug(lid.split(":")[0]) for lid in legislators}
    authored = defaultdict(list)
    for k, b in bills.items():
        for a in b.get("authors", []):
            lid = a["legislator"]
            if isinstance(lid, str):
                authored[lid].append((k, a["role"]))
    cast = defaultdict(dict)  # lid -> bill -> (date, seq, vote) last floor vote
    for k, vs in votes.items():
        for v in vs:
            if "FLOOR" not in v["loc"].upper():
                continue
            for name, m in v["members"].items():
                lid = m.get("legislator")
                if isinstance(lid, str):
                    cur = cast[lid].get(k)
                    stamp = (v["date"], int(v["seq"] or 0))
                    if not cur or stamp >= cur[0]:
                        cast[lid][k] = (stamp, m["vote"])

    # ---------------- bill pages
    def author_line(b):
        out = []
        for a in b.get("authors", []):
            lid = a["legislator"]
            if isinstance(lid, str) and lid in legislators:
                out.append(f'<a href="../legislator/{lid_slug[lid]}.html">{esc(legislators[lid]["name"])}</a> <span class="muted small">({a["role"].replace("_", " ").lower()})</span>')
            else:
                out.append(f'{esc(a["name"])} <span class="muted small">({a["role"].replace("_", " ").lower()})</span>')
        return "; ".join(out) or "—"

    def tag_table(tags, key=None):
        if not tags:
            if key is not None and key not in tagged:
                return '<p class="muted">Not tagged yet.</p>'
            if key is not None and tagged[key].get("refused"):
                return '<p class="muted">Not tagged: the AI model declined to process this bill’s text (its safety filter flagged the subject). Read the digest below.</p>'
            return '<p class="muted">No sub-topic fits this bill, or its digest is too thin to tag.</p>'
        rows = []
        for t in tags:
            s = SUB[t["subtopic"]]
            d = t["direction"]
            g = group(d)
            dot = f'<span class="dot" style="background:var(--{g})"></span>' if g in ORDER else ""
            ev = f'<blockquote>“{esc(t["evidence"])}”</blockquote>' if t.get("evidence") else '<span class="muted small">no quoted support</span>'
            rows.append(f'<tr><td><a href="../topic/{s["topic_id"]}.html">{esc(s["topic"])}</a> → {esc(s["name"])}</td><td>{dot}<b>{esc(DIR_WORD(d)) if d != "not_applicable" else "—"}</b></td>'
                        f'<td>{esc(t["mechanism"].replace("_", " "))}</td><td>{esc(t["funding"])}</td><td>{esc(t["confidence"])}</td><td>{ev}</td></tr>')
        return '<table><thead><tr><th>Topic → sub-topic</th><th>Direction</th><th>Mechanism</th><th>Funding</th><th>Confidence</th><th>Quoted from the digest</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"

    def vote_block(k):
        vs = [v for v in votes.get(k, []) if "FLOOR" in v["loc"].upper()]
        if not vs:
            return '<p class="muted">No recorded floor votes.</p>'
        out = []
        for v in sorted(vs, key=lambda v: (v["date"], int(v["seq"] or 0))):
            by = defaultdict(list)
            for name, m in v["members"].items():
                by[m["vote"]].append(legislators[m["legislator"]]["name"].split(",")[0] if isinstance(m["legislator"], str) and m["legislator"] in legislators else name)
            lists = "".join(f'<p><b>{esc(code)}</b> ({len(names)}): {esc(", ".join(sorted(names)))}</p>' for code, names in sorted(by.items()))
            out.append(f'<details><summary>{esc(v["date"])} · {"Assembly" if v["loc"].upper().startswith("A") else "Senate"} floor · {esc(v["motion"][:90])} · {v["ayes"]}–{v["noes"]}'
                       f'{"–" + str(v["abstain"]) if v["abstain"] else ""} · {esc(v["result"])}</summary>{lists}</details>')
        return "".join(out)

    index = []
    for k, b in sorted(bills.items(), key=lambda kv: (kv[1]["type"], kv[1]["number"])):
        tags = btags.get(k, [])
        summary = tagged.get(k, {}).get("summary", "")
        hist = history.get(k, [])
        hist_rows = "".join(f'<tr><td class="small">{esc(d)}</td><td>{esc(t)}</td></tr>' for d, _, t in hist[-25:][::-1])
        digest = esc(b.get("digest", "")) or '<span class="muted">No digest on file for this bill.</span>'
        body = f"""<p class="small"><a href="../bills.html">← All bills</a></p><h1>{esc(k)} · {esc(b.get("title", ""))}</h1>
<p class="lede">{esc(summary) if summary else ""}</p>
<div class="tiles"><div class="tile"><b style="font-size:18px">{esc(b["status"])}</b><span>Status</span></div><div class="tile"><b style="font-size:18px">{esc(b.get("last_action_date", ""))}</b><span>Last action</span></div>
<div class="tile"><b style="font-size:18px">{esc(b["house"])}</b><span>Currently in</span></div></div>
<p><b>Authors:</b> {author_line(b)}</p>
<h2>Topic tags</h2>{tag_table(tags, k)}
<h2>What the bill does (Legislative Counsel’s digest)</h2><div class="card small">{digest}</div>
<h2>Floor votes</h2>{vote_block(k)}
<h2>Recent actions</h2><table><tbody>{hist_rows}</tbody></table>
<p class="small"><a href="https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id={esc(b["id"])}">Official record on leginfo.legislature.ca.gov ↗</a></p>"""
        (OUT / "bill" / f"{slug(k)}.html").write_text(page(k, body, 1, summary or b.get("title", "")))
        index.append({"k": k, "s": slug(k), "t": b.get("title", ""), "st": b["status"],
                      "tp": sorted({SUB[t["subtopic"]]["topic_id"] for t in tags}), "d": sorted({group(t["direction"]) for t in tags if group(t["direction"]) in ORDER}),
                      "su": summary})

    # ---------------- topic pages
    def bill_li(k, extra=""):
        b = bills[k]
        return f'<li><a href="../bill/{slug(k)}.html">{esc(k)}</a> · {esc(b.get("title", ""))} <span class="chip">{esc(b["status"])}</span>{extra}</li>'

    for tid, t in TOPICS.items():
        rows = []
        for s in t["subtopics"]:
            n = len(set(sub_bills.get(s["id"], [])))
            axis = s["axis"]
            chart = divbar(sub_dir.get(s["id"], Counter())) if axis in ("A", "R") else f'<span class="muted small">{"funding only" if axis == "F" else "no direction"}</span>'
            rows.append(f'<tr><td><a href="#{slug(s["id"])}">{esc(s["name"])}</a></td><td class="n">{n}</td><td style="min-width:240px">{chart}</td></tr>')
        lists = []
        for s in t["subtopics"]:
            ks = sorted(set(sub_bills.get(s["id"], [])), key=lambda k: (bills[k]["type"], bills[k]["number"]))
            if not ks:
                continue
            tagdir = {k: next((x["direction"] for x in btags[k] if x["subtopic"] == s["id"]), "") for k in ks}
            lis = "".join(bill_li(k, f' <span class="chip">{esc(DIR_WORD(tagdir[k]))}</span>' if tagdir[k] and tagdir[k] != "not_applicable" else "") for k in ks[:300])
            more = f'<p class="muted small">Showing the first 300 of {len(ks)}; use <a href="../bills.html">All bills</a> to search.</p>' if len(ks) > 300 else ""
            lists.append(f'<h3 id="{slug(s["id"])}">{esc(s["name"])} <span class="muted small">({len(ks)})</span></h3><ul>{lis}</ul>{more}')
        body = f"""<p class="small"><a href="../index.html">← Overview</a></p><h1>{esc(t["name"])}</h1>
<p class="lede">{len(topic_bills.get(tid, ()))} California bills carry at least one tag under this topic. A bill can appear under several sub-topics.</p>
<h2>Sub-topics and direction</h2>{legend()}<table><thead><tr><th>Sub-topic</th><th class="n">Bills</th><th>Direction of tagged bills</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
<p class="small muted">Direction compares what each bill does on that sub-topic. It describes the bill’s effect, not whether the effect is good or bad.</p>{"".join(lists)}"""
        (OUT / "topic" / f"{tid}.html").write_text(page(t["name"], body, 1))

    # ---------------- legislator pages
    leg_rows = []
    for lid, L in sorted(legislators.items(), key=lambda kv: kv[1]["name"]):
        if not L["active"]:
            continue
        au = authored.get(lid, [])
        vt = cast.get(lid, {})
        aye = sum(1 for _, v in vt.values() if v == "AYE")
        noe = sum(1 for _, v in vt.values() if v == "NOE")
        absn = sum(1 for _, v in vt.values() if v not in ("AYE", "NOE"))
        prof = defaultdict(lambda: defaultdict(int))
        for k, role in au:
            for t in btags.get(k, []):
                if SUB[t["subtopic"]]["axis"] in ("A", "R"):
                    g = group(t["direction"])
                    pole = "R" if g in ("rest1", "rest2") else "P" if g in ("perm1", "perm2") else "N" if g in ("neutral", "mixed") else None
                    if pole:
                        prof[t["subtopic"]][f"au{pole}"] += 1
        for k, (_, v) in vt.items():
            for t in btags.get(k, []):
                if SUB[t["subtopic"]]["axis"] in ("A", "R") and v in ("AYE", "NOE"):
                    g = group(t["direction"])
                    pole = "R" if g in ("rest1", "rest2") else "P" if g in ("perm1", "perm2") else None
                    if pole:
                        prof[t["subtopic"]][("ay" if v == "AYE" else "no") + pole] += 1
        rows = []
        for sid, c in sorted(prof.items(), key=lambda kv: -sum(kv[1].values())):
            s = SUB[sid]
            rows.append(f'<tr><td>{esc(s["topic"])} → {esc(s["name"])}</td><td class="n">{c["auR"]}</td><td class="n">{c["auP"]}</td><td class="n">{c["auN"]}</td>'
                        f'<td class="n">{c["ayR"]}</td><td class="n">{c["ayP"]}</td><td class="n">{c["noR"]}</td><td class="n">{c["noP"]}</td></tr>')
        table = ('<table><thead><tr><th rowspan="2">Sub-topic</th><th colspan="3" class="n">Authored or co-authored</th><th colspan="2" class="n">Voted aye on</th><th colspan="2" class="n">Voted no on</th></tr>'
                 '<tr><th class="n">restrict / tighten</th><th class="n">expand / loosen</th><th class="n">neutral / mixed</th><th class="n">restrict / tighten</th><th class="n">expand / loosen</th><th class="n">restrict / tighten</th><th class="n">expand / loosen</th></tr></thead><tbody>'
                 + "".join(rows) + "</tbody></table>") if rows else '<p class="muted">No tagged bills with a direction yet.</p>'
        au_sorted = sorted(au, key=lambda x: (x[1] != "LEAD_AUTHOR", bills[x[0]]["type"], bills[x[0]]["number"]))
        au_list = "".join(bill_li(k, f' <span class="chip">{esc(role.replace("_", " ").lower())}</span>') for k, role in au_sorted[:400])
        body = f"""<p class="small"><a href="../legislators.html">← All legislators</a></p><h1>{esc(L["name"])}</h1>
<p class="lede"><span class="party {L["party"]}">{esc({"DEM": "Democrat", "REP": "Republican"}.get(L["party"], L["party"]))}</span> · {esc(L["house"])} · District {esc(re.sub(r"^[A-Z]+0*", "", lid.split(":")[0]))}</p>
<div class="tiles"><div class="tile"><b>{len(au)}</b><span>bills authored or co-authored</span></div><div class="tile"><b>{len(vt)}</b><span>bills with a recorded floor vote</span></div>
<div class="tile"><b>{aye}</b><span>aye votes</span></div><div class="tile"><b>{noe}</b><span>no votes</span></div></div>
<h2>Record by sub-topic and direction</h2>{table}
<p class="note small">These are counts of what this legislator authored and how they voted on tagged bills, with the bills linked below. A co-author may sign on to a bill they have reservations about, and a vote reflects one amendment stage. Most bills that reach a floor vote pass with large majorities and almost every member votes aye, so aye counts mostly mirror what reached the floor; authorship and no votes are the more distinctive signals. Treat the counts as evidence, not as a rating. Only floor votes are counted; committee votes are not matched to members yet.</p>
<h2>Bills authored ({len(au)})</h2><ul>{au_list}</ul>"""
        (OUT / "legislator" / f"{lid_slug[lid]}.html").write_text(page(L["name"], body, 1))
        leg_rows.append((L, lid, len(au), len(vt)))
    rows = "".join(f'<tr><td><a href="legislator/{lid_slug[lid]}.html">{esc(L["name"])}</a></td><td><span class="party {L["party"]}">{esc(L["party"])}</span></td><td>{esc(L["house"])}</td>'
                   f'<td>{esc(re.sub(r"^[A-Z]+0*", "", lid.split(":")[0]))}</td><td class="n">{na}</td><td class="n">{nv}</td></tr>' for L, lid, na, nv in leg_rows)
    (OUT / "legislators.html").write_text(page("Legislators", f'<h1>Legislators</h1><p class="lede">{len(leg_rows)} members of the 2025–26 California Legislature.</p>'
        f'<table><thead><tr><th>Name</th><th>Party</th><th>House</th><th>District</th><th class="n">Bills authored</th><th class="n">Bills voted on (floor)</th></tr></thead><tbody>{rows}</tbody></table>'))

    # ---------------- overview
    counts = sorted(((len(topic_bills.get(tid, ())), tid) for tid in TOPICS), reverse=True)
    top = counts[0][0] or 1
    bar = "".join(f'<div class="row"><a href="topic/{tid}.html">{esc(TOPICS[tid]["name"])}</a><div class="track" title="{esc(TOPICS[tid]["name"])}: {n} bills"><div class="fill" style="width:{100 * n / top:.1f}%"></div></div><div class="v">{n}</div></div>' for n, tid in counts)
    status = Counter(b["status"] for b in bills.values())
    body = f"""<h1>California legislation by topic and direction</h1>
<p class="lede">Every bill in California’s 2025–26 session, sorted into topics, with a read on which way each bill pushes: does it expand or restrict, tighten or loosen, and where does the money go. Then what each legislator authored and how they voted.</p>
<div class="tiles"><div class="tile"><b>{len(bills):,}</b><span>bills</span></div><div class="tile"><b>{n_tagged:,}</b><span>with topic tags</span></div><div class="tile"><b>{len(leg_rows)}</b><span>legislators</span></div>
<div class="tile"><b>{status.get("Chaptered", 0):,}</b><span>signed into law (chaptered)</span></div></div>
<h2>Bills by topic</h2><p class="small muted">A bill counts once under each topic it touches, so bars add up to more than the number of bills.</p><div class="bars">{bar}</div>
<h2>Where to start</h2><ul><li><a href="bills.html">Search all bills</a> by words, topic, status or direction.</li><li><a href="legislators.html">Legislators</a>: authorship and floor votes by sub-topic and direction.</li><li><a href="method.html">How it works</a>, and what the labels can and cannot tell you.</li></ul>"""
    (OUT / "index.html").write_text(page("California by topic", body))

    # ---------------- bills search page
    opts_t = "".join(f'<option value="{tid}">{esc(t["name"])}</option>' for tid, t in TOPICS.items())
    opts_s = "".join(f"<option>{esc(s)}</option>" for s in sorted(status))
    opts_d = "".join(f'<option value="{g}">{GROUP_LABEL[g]}</option>' for g in ORDER)
    js = """const D=%s;const TN=%s;const GL=%s;
const q=document.getElementById('q'),tp=document.getElementById('tp'),st=document.getElementById('st'),dr=document.getElementById('dr'),out=document.getElementById('out'),cnt=document.getElementById('cnt');
function esc(s){return s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function run(){const w=q.value.toLowerCase().trim().split(/\\s+/).filter(Boolean);let n=0,h='';
for(const b of D){if(tp.value&&!b.tp.includes(tp.value))continue;if(st.value&&b.st!==st.value)continue;if(dr.value&&!b.d.includes(dr.value))continue;
const hay=(b.k+' '+b.t+' '+b.su).toLowerCase();if(w.some(x=>!hay.includes(x)))continue;n++;
if(n<=200)h+='<tr><td><a href="bill/'+b.s+'.html">'+esc(b.k)+'</a></td><td>'+esc(b.t)+'<div class="muted small">'+esc(b.su)+'</div></td><td>'+esc(b.st)+'</td><td>'+b.tp.map(t=>'<span class="chip">'+esc(TN[t])+'</span>').join('')+'</td></tr>'}
out.innerHTML=h;cnt.textContent=n+' bills'+(n>200?' (showing the first 200; narrow the search)':'')}
[q,tp,st,dr].forEach(e=>e.addEventListener('input',run));run();""" % (json.dumps(index, separators=(",", ":"), ensure_ascii=False), json.dumps({tid: t["name"] for tid, t in TOPICS.items()}), json.dumps(GROUP_LABEL))
    (OUT / "bills.html").write_text(page("All bills", f"""<h1>All bills</h1><p class="lede">Search {len(bills):,} California bills.</p>
<div class="filters"><input id="q" placeholder="Search bill number, title or summary" aria-label="Search"><select id="tp" aria-label="Topic"><option value="">Any topic</option>{opts_t}</select>
<select id="st" aria-label="Status"><option value="">Any status</option>{opts_s}</select><select id="dr" aria-label="Direction"><option value="">Any direction</option>{opts_d}</select></div>
<p class="muted small" id="cnt"></p><table><thead><tr><th>Bill</th><th>Title</th><th>Status</th><th>Topics</th></tr></thead><tbody id="out"></tbody></table><script>{js}</script>"""))

    # ---------------- method
    taxrows = "".join(f'<li><b>{esc(t["name"])}</b>: ' + ", ".join(esc(s["name"]) for s in t["subtopics"]) + "</li>" for t in TAX["topics"])
    model = json.loads((DATA / "tags.json").read_text()).get("model", "")
    (OUT / "method.html").write_text(page("How it works", f"""<h1>How it works</h1>
<h2>What is labelled</h2><p>Each California bill gets one or more tags. A tag has a <b>sub-topic</b> from a fixed two-level list ({len(TOPICS)} topics, {len(SUB)} sub-topics), a <b>direction</b> on that sub-topic, a <b>mechanism</b> (for example a ban, a licensing rule, a tax incentive, a study) and a <b>funding</b> note (increases, decreases, none).</p>
<h2>Direction</h2><p>Direction describes what the bill does, not whether that is good or bad. For rights and access sub-topics it is expands or restricts. For regulation sub-topics it is tightens or loosens. Funding-only sub-topics have no direction. Studies, assessments, voluntary programs and rules that only assign responsibility are labelled neutral.</p>
<h2>Evidence</h2><p>Every direction call must quote a sentence from the Legislative Counsel’s digest of the bill. If the quoted sentence is not in the digest, the call is thrown away and shown as unclear.</p>
<h2>Who does the labelling</h2><p>An AI model ({esc(model)}) reads each bill’s title and digest and applies the list above. It is fast and cheap but not perfect: in a 50-bill test it agreed with a larger model on about 86% of direction calls. Bills without a digest are tagged from the title alone and usually come out unclear on direction. The model declined to process one bill (a biosecurity bill) and it is shown untagged. Treat labels as a guide to read the bill, not a substitute.</p>
<h2>Legislators</h2><p>Legislator pages count what each member authored or co-authored and how they voted on the floor, by sub-topic and direction, with every bill linked. Committee votes are not yet matched to members. A co-author can sign on for many reasons, so counts are evidence, not a rating, and the site computes no overall score.</p>
<h2>Topics</h2><ul>{taxrows}</ul>"""))
    print(f"built {len(bills)} bill pages, {len(TOPICS)} topic pages, {len(leg_rows)} legislator pages; {n_tagged} bills with tags")


if __name__ == "__main__":
    sys.exit(main())
