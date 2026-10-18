"""Find near-duplicate bills across states (model legislation, copycats) by TF-IDF cosine on title + summary."""
import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

GENERIC = re.compile(r"\b(budget|appropriation|appropriations|supplemental|omnibus|trailer bill|tax rates?|fiscal year|bond act|bonds?|commending|honoring|congratulating|recognizing|memorializing|designating)\b", re.I)
VAGUE = re.compile(r"gives no details|no details|text provided|not specif|does not say|unclear what|likely ", re.I)
STOP_STATE = re.compile(r"\b(california|washington|oregon|massachusetts|florida|district of columbia|commonwealth|d\.c\.|dc|state|department|legislature|council)\b", re.I)


def clean(t):
    t = STOP_STATE.sub(" ", t.lower())
    t = re.sub(r"\b(bill|act|section|sections|code|statutes|chapter|amends|adds|repeals|would|requires|require|requiring|relating|to|of|the|and|for|a|an|in|by|on|or)\b", " ", t)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def find_matches(A, min_sim=0.62, max_per_state=3):
    docs, ref = [], []   # ref: (state, key)
    for code, S in A.items():
        for k, b in S["bills"].items():
            if not b["tags"] or b["ceremonial"] or not b["summary"] or GENERIC.search(b["title"] + " " + b["summary"]) or VAGUE.search(b["summary"]):
                continue
            docs.append(clean(b["title"] + " " + b["summary"]))
            ref.append((code, k))
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_df=0.03, sublinear_tf=True, dtype=np.float32)
    X = vec.fit_transform(docs)
    codes = sorted({c for c, _ in ref})
    idx = {c: np.array([i for i, (cc, _) in enumerate(ref) if cc == c]) for c in codes}
    pairs = []
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            S = (X[idx[a]] @ X[idx[b]].T).tocoo()
            m = S.data >= min_sim
            for r, c, v in zip(S.row[m], S.col[m], S.data[m]):
                pairs.append((idx[a][r], idx[b][c], float(v)))
    # union-find over cross-state links
    parent = list(range(len(ref)))

    def f(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, j, v in pairs:
        parent[f(i)] = f(j)
    groups = {}
    for i in range(len(ref)):
        groups.setdefault(f(i), []).append(i)
    sims = {}
    for i, j, v in pairs:
        sims[f(i)] = sims.get(f(i), []) + [v]
    out = []
    for g, members in groups.items():
        states = {ref[i][0] for i in members}
        if len(states) < 2 or g not in sims:
            continue
        per = {}
        for i in members:
            per.setdefault(ref[i][0], []).append((ref[i][1], i))
        if any(len(v) > max_per_state for v in per.values()) or len(members) > 14:
            continue   # chained, probably not one family
        out.append({"members": [(ref[i][0], ref[i][1]) for i in members], "states": sorted(states), "sim": float(np.mean(sims[g])), "n": len(members)})
    out.sort(key=lambda g: (-len(g["states"]), -g["sim"]))
    return out
