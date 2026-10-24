# -*- coding: utf-8 -*-
"""Moderation of corrections proposed "for everyone".

Reads open GitHub issues titled "[correction] ...", re-checks each proposal with the SAME code as the plugin
(whitelist, at least two condition items, spec check, fingerprint), counts distinct installations per fingerprint
and adds a correction to corrections/global.json once MIN_VOTES installations proposed it.
A correction that contradicts an accepted one (prefer vs avoid of the same material for the same condition)
is reported as a conflict for a human to decide.

Usage (from the repository root):  python corrections/moderate.py [--repo owner/name] [--votes 3]
Then commit corrections/global.json. Reading public issues needs no token.
"""
import argparse
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "plugin", "AIAssistant"))
from agent import corrections

GLOBAL_PATH = os.path.join(HERE, "global.json")


def fetch_issues(repo):
    url = "https://api.github.com/repos/%s/issues?state=open&per_page=100" % repo
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "moderate.py"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return [i for i in json.loads(r.read().decode("utf-8")) if (i.get("title") or "").startswith("[correction]")]


def parse(issue):
    m = re.search(r"```json\s*(\{.*?\})\s*```", issue.get("body") or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="hikinokomora/MCP-STE-Slicer")
    ap.add_argument("--votes", type=int, default=3)
    args = ap.parse_args()

    accepted = json.load(open(GLOBAL_PATH, encoding="utf-8")) if os.path.exists(GLOBAL_PATH) else []
    known = {c["fingerprint"] for c in accepted}
    votes, samples = {}, {}
    for issue in fetch_issues(args.repo):
        data = parse(issue)
        if not data:
            print("#%s: no correction JSON, skipped" % issue["number"])
            continue
        corr = {"id": data.get("fingerprint", "")[:12], "conditions": data.get("conditions"), "action": data.get("action"),
                "comment": corrections.clean_comment(data.get("comment")), "context": data.get("context") or {},
                "fingerprint": data.get("fingerprint"), "created": data.get("created")}
        problems = corrections.validate(corr)
        if problems:
            print("#%s: rejected: %s" % (issue["number"], "; ".join(problems)))
            continue
        fp = corr["fingerprint"]
        votes.setdefault(fp, set()).add(str(data.get("install_id") or "issue-%s" % issue["number"]))
        samples.setdefault(fp, (corr, []))[1].append(issue["number"])

    changed = False
    for fp, voters in votes.items():
        corr, issues = samples[fp]
        text = corrections.describe(corr)
        if fp in known:
            print("%s: already accepted (issues %s)" % (text, issues))
            continue
        kind, material = list(corr["action"].items())[0]
        opposite = "avoid" if kind == "prefer" else "prefer"
        conflict = [c for c in accepted if c["conditions"] == corr["conditions"] and c["action"].get(opposite) == material]
        if conflict:
            print("%s: CONFLICT with an accepted correction, needs a human (issues %s)" % (text, issues))
            continue
        if len(voters) >= args.votes:
            accepted.append(dict(corr, scope="global"))
            known.add(fp)
            changed = True
            print("%s: ACCEPTED (%d installations, issues %s)" % (text, len(voters), issues))
        else:
            print("%s: %d of %d votes (issues %s)" % (text, len(voters), args.votes, issues))
    if changed:
        with open(GLOBAL_PATH, "w", encoding="utf-8") as f:
            json.dump(accepted, f, ensure_ascii=False, indent=2)
        print("global.json updated - commit and push it; plugins load it at start.")


if __name__ == "__main__":
    main()
