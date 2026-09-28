#!/usr/bin/env python3
"""Back up issues + comments of a public repo (stdlib only).
Source repo is fixed in SOURCE_REPO below.
Usage:
  python3 scripts/backup_issues.py --out backup
  # quick local test (20 issues, no comments):
  python3 scripts/backup_issues.py --out /tmp/bk --max-issues 20 --no-comments
"""
import argparse
import concurrent.futures
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import API, get_token, paginate_rest, rest_get, write_json
from config import SOURCE_REPO



def parent_number(i: dict) -> int | None:
    url = i.get("parent_issue_url")
    if not url:
        return None
    try:
        return int(str(url).rstrip("/").split("/")[-1])
    except ValueError:
        return None


def slim_issue(i: dict) -> dict:
    return {
        "number": i.get("number"),
        "title": i.get("title"),
        "state": i.get("state"),
        "state_reason": i.get("state_reason"),
        "is_pull_request": "pull_request" in i,
        "labels": [l.get("name") for l in (i.get("labels") or [])],
        "assignees": [a.get("login") for a in (i.get("assignees") or [])],
        "milestone": (i.get("milestone") or {}).get("title") if i.get("milestone") else None,
        "created_at": i.get("created_at"),
        "updated_at": i.get("updated_at"),
        "closed_at": i.get("closed_at"),
        "author": ((i.get("user") or {}).get("login")),
        "comments_count": i.get("comments", 0),
        "body": i.get("body"),
        "url": i.get("html_url"),
        "parent": parent_number(i),
        "sub_issues_summary": i.get("sub_issues_summary"),
        "sub_issues": [],
        "issue_field_values": i.get("issue_field_values"),
        "issue_dependencies": i.get("issue_dependencies_summary"),
    }


def slim_comment(c: dict) -> dict:
    return {
        "id": c.get("id"),
        "author": ((c.get("user") or {}).get("login")),
        "created_at": c.get("created_at"),
        "updated_at": c.get("updated_at"),
        "body": c.get("body"),
        "url": c.get("html_url"),
    }


def fetch_comments(repo: str, number: int, token: str | None, full: bool):
    url = f"{API}/repos/{repo}/issues/{number}/comments?per_page=100&page=1"
    out, page_url, page = [], url, 0
    from common import parse_link_next
    while page_url and page < 20:  # max 2000 comments/issue, logged beyond that
        page += 1
        batch, headers = rest_get(page_url, token)
        out.extend(batch if isinstance(batch, list) else [batch])
        page_url = parse_link_next(headers.get("Link"))
    return out if full else [slim_comment(c) for c in out]


def fetch_sub_issue_numbers(repo: str, number: int, token: str | None):
    """Children issue numbers (numbers only). Called for parents only."""
    url = f"{API}/repos/{repo}/issues/{number}/sub_issues?per_page=100&page=1"
    out, page_url, page = [], url, 0
    from common import parse_link_next
    while page_url and page < 20:  # max 2000 children/issue
        page += 1
        batch, headers = rest_get(page_url, token)
        items = batch if isinstance(batch, list) else [batch]
        out.extend(x.get("number") for x in items if x.get("number") is not None)
        page_url = parse_link_next(headers.get("Link"))
    return sorted(set(out))


def run(repo: str, out: str, token: str | None, full: bool = False,
        max_pages: int = 600, max_issues: int = 0, no_comments: bool = False,
        since: str | None = None, workers: int = 8) -> dict:
    q = f"https://api.github.com/repos/{repo}/issues?state=all&per_page=100&page=1"
    if since:
        q += f"&since={since}"
    print(f"[issues] {repo} (full={full}, since={since})...")
    raw = paginate_rest(q, token, max_pages=max_pages)
    if max_issues and len(raw) > max_issues:
        raw = raw[:max_issues]
        print(f"  test mode: limited to {max_issues} issues")
    data = raw if full else [slim_issue(i) for i in raw]
    if full:
        for item in data:
            item["parent"] = parent_number(item)
            item.setdefault("sub_issues", [])

    if not no_comments:
        # fetch comments only where comments_count > 0 (saves ~70% of calls)
        targets = []
        for idx, item in enumerate(data):
            n = (raw[idx].get("comments", 0) if full else item.get("comments_count", 0)) or 0
            if n > 0:
                targets.append((item["number"], n, idx))
        print(f"  comments to download for {len(targets)}/{len(data)} issues...")
        ok = err = 0
        if targets and token is None:
            print("  no token: limit is 60 req/hour, BACKUP_TOKEN is required. Continuing anyway (slow, may fail).")

        def _one(t):
            number, _, idx = t
            try:
                return idx, fetch_comments(repo, number, token, full), None
            except Exception as e:
                return idx, [], str(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            for idx, comments, e in ex.map(_one, targets):
                if e:
                    err += 1
                    data[idx]["comments_fetch_error"] = e[:200]
                    data[idx]["comments"] = []
                else:
                    ok += 1
                    data[idx]["comments"] = comments
        for item in data:
            item.setdefault("comments", [])
        print(f"  comments ok: {ok}, errors: {err}")
    else:
        for item in data:
            item["comments"] = []
        print("  comments skipped (--no-comments)")

    # second pass: fetch sub-issue numbers for parents
    parents = [(idx, item) for idx, item in enumerate(data)
               if (item.get("sub_issues_summary") or {}).get("total", 0) > 0]
    if parents:
        print(f"  sub-issues to fetch for {len(parents)}/{len(data)} parent issues...")
        ok2 = err2 = 0

        def _one_sub(t):
            idx, item = t
            try:
                return idx, fetch_sub_issue_numbers(repo, item["number"], token), None
            except Exception as e:
                return idx, [], str(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            for idx, children, e in ex.map(_one_sub, parents):
                if e:
                    err2 += 1
                    data[idx]["sub_issues_fetch_error"] = e[:200]
                    data[idx]["sub_issues"] = []
                else:
                    ok2 += 1
                    data[idx]["sub_issues"] = children
        print(f"  sub-issues ok: {ok2}, errors: {err2}")

    size = write_json(Path(out) / "issues.json", data)
    print(f"  {len(data)} issues -> {out}/issues.json ({size/1024:.1f} KB)")
    return {"count": len(data), "bytes": size}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="backup")
    ap.add_argument("--token", default=None)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--max-pages", type=int, default=600)
    ap.add_argument("--max-issues", type=int, default=0, help="0 = all, N = first N only (local tests)")
    ap.add_argument("--no-comments", action="store_true")
    ap.add_argument("--since", default=None, help="e.g. 2026-09-01T00:00:00Z (incremental, 50k scale)")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    run(SOURCE_REPO, a.out, get_token(a.token), full=a.full, max_pages=a.max_pages,
        max_issues=a.max_issues, no_comments=a.no_comments, since=a.since, workers=a.workers)


if __name__ == "__main__":
    main()
