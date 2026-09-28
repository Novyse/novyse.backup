#!/usr/bin/env python3
"""Back up releases of a public repo (stdlib only).
Usage:
  python3 scripts/backup_releases.py --out backup
  python3 scripts/backup_releases.py --out backup --full --max-pages 2
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_token, paginate_rest, write_json


def slim_release(r: dict) -> dict:
    return {
        "tag_name": r.get("tag_name"),
        "name": r.get("name"),
        "body": r.get("body"),
        "published_at": r.get("published_at"),
        "created_at": r.get("created_at"),
        "draft": r.get("draft"),
        "prerelease": r.get("prerelease"),
        "target_commitish": r.get("target_commitish"),
        "assets": [
            {"name": a.get("name"), "size": a.get("size"),
             "download_count": a.get("download_count"),
             "browser_download_url": a.get("browser_download_url")}
            for a in (r.get("assets") or [])
        ],
    }


def run(repo: str, out: str, token: str | None, full: bool = False,
        max_pages: int = 600) -> dict:
    base = f"https://api.github.com/repos/{repo}/releases?per_page=100&page=1"
    print(f"[releases] {repo} (full={full})...")
    raw = paginate_rest(base, token, max_pages=max_pages)
    data = raw if full else [slim_release(r) for r in raw]
    size = write_json(Path(out) / "releases.json", data)
    print(f"  {len(data)} releases -> {out}/releases.json ({size/1024:.1f} KB)")
    return {"count": len(data), "bytes": size}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="backup")
    ap.add_argument("--token", default=None)
    ap.add_argument("--full", action="store_true", help="save full objects instead of slim")
    ap.add_argument("--max-pages", type=int, default=600)
    a = ap.parse_args()
    run(SOURCE_REPO, a.out, get_token(a.token), full=a.full, max_pages=a.max_pages)


if __name__ == "__main__":
    main()
