# StateTrack

Every state bill, tagged by topic and direction, with legislator profiles built from sponsorship and recorded votes.
Demo: California (2025–26 session).

## What it answers
- How many bills are there on a high-level topic (guns, health care, housing, AI and technology, and so on)?
- Which way does a bill push on an issue: does it expand or restrict it, tighten or loosen the rules, add or cut funding?
- Where does each legislator stand, judged from what they sponsor and how they vote?

## Principles
- Direction describes what a bill does, never a viewpoint. Every call is backed by a quoted line from the bill text.
- Legislator positions come from their actions (authorship, co-sponsorship, floor votes), with the bills linked. No single score without the evidence behind it.
- Topic tags from titles are approximate and labelled as such.

## Layout
- `taxonomy/taxonomy.json` the two-level topic tree and the direction axes (draft, under review)
- `data/ca/` California bills, legislators, votes, action history (source: the official bulk file, via the shared bill database)
- `scripts/` data and site builders
- `.github/workflows/` connection checks and publishing

## Data
The full bill catalogue (all states) is produced by the shared bill database project and published to Cloudflare R2.
The California demo files are copied here until R2 is connected.
