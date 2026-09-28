#!/usr/bin/env python3
"""Main script: runs releases + issues + roadmap.
Usage:
  BACKUP_TOKEN=xxx python3 scripts/backup_all.py --out backup
  # quick local test without stressing limits (60 req/hour without token):
  python3 scripts/backup_all.py --out /tmp/bk-test --max-releases-pages 1 --max-issues 20 --no-comments --max-items 20
  # NOTE: roadmap needs BACKUP_TOKEN; without a token it is skipped with a warning.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_token
import backup_releases as mod_rel
import backup_issues as mod_iss
import backup_roadmap as mod_map
from config import ORG, PROJECT_NUMBER, SOURCE_REPO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="backup")
    ap.add_argument("--token", default=None)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--since", default=None)
    ap.add_argument("--max-releases-pages", type=int, default=600)
    ap.add_argument("--max-issues", type=int, default=0)
    ap.add_argument("--max-issue-pages", type=int, default=600)
    ap.add_argument("--no-comments", action="store_true")
    ap.add_argument("--max-items", type=int, default=0)
    ap.add_argument("--skip", default="", help="e.g. roadmap,issues,releases comma-separated")
    a = ap.parse_args()
    token = get_token(a.token)
    skip = {s.strip() for s in a.skip.split(",") if s.strip()}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    results, errors = {}, {}
    if "releases" not in skip:
        try:
            results["releases"] = mod_rel.run(SOURCE_REPO, str(out), token, full=a.full,
                                              max_pages=a.max_releases_pages)
        except Exception as e:
            errors["releases"] = str(e)[:300]
            print(f"  releases failed: {e}")
    if "issues" not in skip:
        try:
            results["issues"] = mod_iss.run(SOURCE_REPO, str(out), token, full=a.full,
                                            max_pages=a.max_issue_pages, max_issues=a.max_issues,
                                            no_comments=a.no_comments, since=a.since)
        except Exception as e:
            errors["issues"] = str(e)[:300]
            print(f"  issues failed: {e}")
    if "roadmap" not in skip:
        if not token:
            print("  roadmap skipped: BACKUP_TOKEN is required for GraphQL (even public projects).")
            errors["roadmap"] = "skipped: missing token"
        else:
            try:
                results["roadmap"] = mod_map.run(ORG, PROJECT_NUMBER, str(out), token,
                                                 max_items=a.max_items)
            except Exception as e:
                errors["roadmap"] = str(e)[:300]
                print(f"  roadmap failed: {e}")

    print(f"\n=== done: {json.dumps(results)} errors={json.dumps(errors)} ===")
    sys.exit(1 if errors and len(errors) == (3 - len(skip)) else 0)


if __name__ == "__main__":
    main()
