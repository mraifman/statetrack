#!/usr/bin/env python3
"""Generate taxonomy/taxonomy.json (v1.1) from the approved list. Axis codes: A access/rights, R regulation, F funding only, N none."""
import json, re, sys
from pathlib import Path

TREE = [
 ("Health care", [
  ("Reproductive health and abortion", "A"), ("Gender-affirming and transgender health care", "A"), ("Medicaid and public coverage", "A"),
  ("Private insurance rules and mandates", "R"), ("Drug pricing and pharmacy", "R"), ("Hospitals and providers (certificate of need, scope of practice)", "R"),
  ("Mental health and substance use treatment", "A"), ("Public health, vaccines and emergency measures", "R"),
  ("Long-term care and disability services", "F"), ("Health care workforce and funding", "F")]),
 ("Guns and weapons", [
  ("Carry and ownership, including public places and schools", "A"), ("Purchase, licensing and dealers", "R"), ("Weapon and magazine types", "R"),
  ("Safe storage and extreme-risk orders", "R"), ("Violence prevention programs", "F")]),
 ("Children and families", [
  ("Child welfare and foster care", "F"), ("Child care and early education", "A"), ("Parental rights", "A"),
  ("Kids' online safety and age verification", "R"), ("Juvenile justice", "R"), ("Child support, custody and family law", "N"), ("Children's programs and funding", "F")]),
 ("Housing", [
  ("Zoning, land use and short-term rentals", "R"), ("Rent regulation and tenant protections", "R"), ("Affordable housing programs", "F"),
  ("Homelessness (services vs. encampment rules)", "A"), ("Building codes and construction", "R"), ("Mortgage, ownership and property transactions", "N")]),
 ("AI and technology", [
  ("AI safety and oversight", "R"), ("AI development and adoption (incentives vs. burdens)", "A"), ("Government use of AI", "A"), ("Deepfakes and synthetic media", "R"),
  ("AI in employment and consumer decisions", "R"), ("Data centers and compute", "A"), ("Data privacy and security", "R"),
  ("Social media and online platforms", "R"), ("Broadband and telecom", "A")]),
 ("Education", [
  ("K-12 funding", "F"), ("School choice and vouchers", "A"), ("Curriculum and classroom content", "R"), ("Higher education costs and aid", "F"),
  ("Campus policy (speech, DEI, tenure)", "R"), ("Teacher workforce and pay", "F"), ("School safety, discipline and phones", "R")]),
 ("Taxes and budget", [
  ("Income taxes", "F"), ("Property taxes", "F"), ("Sales and excise taxes", "F"), ("Business tax incentives and credits", "F"),
  ("State budget and appropriations", "F"), ("Bonds, debt and pensions funding", "F")]),
 ("Elections and voting", [
  ("Voter registration and access (mail voting, early voting)", "A"), ("Voter ID and election security", "R"), ("Redistricting", "N"),
  ("Campaign finance", "R"), ("Election administration and officials", "N")]),
 ("Transportation", [
  ("Autonomous vehicles", "A"), ("Driver-assistance systems (ADAS)", "R"), ("Traffic safety and enforcement (speed cameras, DUI)", "R"), ("Electric vehicles and charging", "A"),
  ("Rideshare, scooters and micromobility", "R"), ("Drones and aviation", "R"), ("Transit and infrastructure funding", "F"), ("Vehicle registration, licensing and fees", "N")]),
 ("Environment and energy", [
  ("Climate and emissions", "R"), ("Clean energy (renewables, storage, nuclear)", "A"), ("Fossil fuels, pipelines and mining", "A"),
  ("Utility regulation and rates", "R"), ("Environmental permitting and review", "R"), ("Water, land and wildlife protection", "R"), ("Public lands and conservation funding", "F")]),
 ("Criminal justice", [
  ("Sentencing and penalties", "R"), ("Policing and accountability", "R"), ("Bail, pretrial and courts", "R"),
  ("Drug policy (cannabis, decriminalization)", "A"), ("Corrections and reentry", "A"), ("Victims' rights", "A")]),
 ("Labor and employment", [
  ("Minimum wage and wage rules", "R"), ("Unions and collective bargaining", "A"), ("Worker safety and protections", "R"),
  ("Worker benefits (paid leave, unemployment insurance)", "A"), ("Gig work and independent contractors", "R"), ("Occupational licensing", "R")]),
 ("Immigration", [
  ("State cooperation with federal enforcement, including employment verification", "R"), ("Benefits, education and services for immigrants", "A")]),
 ("Civil rights and liberties", [
  ("Anti-discrimination protections, including DEI programs", "A"), ("Speech and religion", "A"),
  ("Gender identity policies (non-medical)", "A"), ("Records, surveillance and civil liberties", "R")]),
 ("Consumer protection and business", [
  ("Consumer protection and fees", "R"), ("Insurance market regulation", "R"), ("Banking, lending and crypto", "R"),
  ("Business licensing and regulation", "R"), ("Gambling and sports betting", "A"), ("Alcohol, tobacco and vaping", "R"), ("Food and agriculture", "N")]),
 ("Government and administration", [
  ("State agencies and programs", "N"), ("Local control and preemption", "A"), ("Ethics and transparency", "R"),
  ("Public employees and pensions", "F"), ("State constitution and ballot measures", "N"), ("Emergency powers", "N")]),
 ("Not a policy topic", [("Ceremonial and commemorative measures", "N")]),
]

NOTES = {
 "Curriculum and classroom content": "restricts = bans or limits what may be taught; expands = requires or adds subject matter",
 "Local control and preemption": "expands = gives local governments more authority; restricts = preempts or limits it",
 "AI development and adoption (incentives vs. burdens)": "expands = promotes, funds or incentivizes; restricts = burdens or limits",
 "Data centers and compute": "expands = facilitates or incentivizes; restricts = limits or adds conditions",
 "Homelessness (services vs. encampment rules)": "expands = more services or protections; restricts = more enforcement against people who are homeless",
 "Zoning, land use and short-term rentals": "loosens = allows more building or more rentals; tightens = limits it",
 "Autonomous vehicles": "driverless or automated driving systems that operate without a human driver continuously in control (SAE levels 3 to 5): expands = allows, facilitates or incentivizes; restricts = bans, limits or adds conditions. Driver-assistance features that need a human to supervise belong under Driver-assistance systems, not here",
 "Driver-assistance systems (ADAS)": "partially automated features where a human driver must stay in control and supervise (SAE level 2: lane-keeping, adaptive cruise control, 'driver support'): tightens = adds requirements, limits, reporting or liability; loosens = reduces them. A drunk-driving or other traffic offense by a human using these features is Traffic safety, not ADAS, unless the bill regulates the feature itself",
 "Ceremonial and commemorative measures": "naming, honoring, commemorating or resolutions with no policy effect; tag these and nothing else",
}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"\(.*?\)", "", s).lower()).strip("_")


def main():
    topics, seen = [], set()
    for tname, subs in TREE:
        tid = slug(tname)
        t = {"id": tid, "name": tname, "subtopics": []}
        if tid == "not_a_policy_topic":
            t["excluded"] = True
        for sname, axis in subs:
            sid = f"{tid}.{slug(sname)}"
            assert sid not in seen, sid
            seen.add(sid)
            sub = {"id": sid, "name": sname, "axis": axis}
            if sname in NOTES:
                sub["note"] = NOTES[sname]
            t["subtopics"].append(sub)
        topics.append(t)
    tax = {"version": "1.1",
           "note": "Direction is measured against the status quo: current California law as described in the digest. Permissive = moves toward more permission, access or fewer rules; restrictive = toward less permission or more rules.",
           "axes": {"A": {"label": "Access / rights", "poles": ["restricts", "expands"]}, "R": {"label": "Regulation", "poles": ["loosens", "tightens"]},
                    "F": {"label": "Funding only", "poles": []}, "N": {"label": "None", "poles": []}},
           "directions_by_axis": {"A": ["strongly_restricts", "restricts", "mixed", "neutral", "expands", "strongly_expands", "unclear"],
                                  "R": ["strongly_loosens", "loosens", "mixed", "neutral", "tightens", "strongly_tightens", "unclear"],
                                  "F": ["not_applicable"], "N": ["not_applicable"]},
           "funding": ["increases", "decreases", "none", "unclear"], "topics": topics}
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "taxonomy/taxonomy.json"
    out.write_text(json.dumps(tax, indent=1))
    print(len(topics), "topics,", sum(len(t["subtopics"]) for t in topics), "sub-topics")


if __name__ == "__main__":
    main()
