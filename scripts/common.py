"""Shared helpers (stdlib only) for GitHub backups."""
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
UA = "novyse-backup/1.0 (+https://github.com/novyse)"


def get_token(explicit: str | None = None) -> str | None:
    tok = explicit or os.environ.get("BACKUP_TOKEN")
    return tok.strip() if tok and tok.strip() else None


def _headers(token: str | None) -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _sleep_on_ratelimit(headers, status: int):
    """Return seconds to wait when rate-limited, else None."""
    reset = None
    try:
        reset = headers.get("x-ratelimit-reset")
    except Exception:
        pass
    retry_after = None
    try:
        retry_after = headers.get("Retry-After")
    except Exception:
        pass
    if status in (403, 429):
        if retry_after:
            try:
                return max(1, int(retry_after))
            except ValueError:
                return 60
        if reset:
            try:
                wait = int(reset) - int(time.time()) + 5
                return max(5, min(wait, 600))
            except ValueError:
                return 60
        return 60
    return None


def rest_get(url: str, token: str | None, timeout: int = 30, retries: int = 5):
    """GET with retries on 403/429/5xx. Returns (data, resp_headers)."""
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=_headers(token))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp), dict(resp.headers)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            wait = _sleep_on_ratelimit(e.headers or {}, e.code)
            if wait is not None and attempt < retries - 1:
                print(f"  rate-limit {e.code} on {url[:90]}... waiting {wait}s (attempt {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            if e.code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"HTTP {e.code} on {url}: {body}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"GET failed after {retries} attempts on {url}: {last_err}")


def parse_link_next(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        m = re.search(r'<([^>]+)>\s*;\s*rel="([^"]+)"', part.strip())
        if m and m.group(2) == "next":
            return m.group(1)
    return None


def paginate_rest(first_url: str, token: str | None, max_pages: int = 600, log_every: int = 5):
    """Follow Link: rel=next. Returns the full list."""
    out, url, page = [], first_url, 0
    while url and page < max_pages:
        page += 1
        data, headers = rest_get(url, token)
        if isinstance(data, list):
            out.extend(data)
            if page == 1 or page % log_every == 0:
                print(f"  ... page {page}: {len(data)} items (total {len(out)})")
        else:
            out.append(data)
            break
        url = parse_link_next(headers.get("Link"))
    return out


def graphql(query: str, variables: dict, token: str, timeout: int = 30, retries: int = 5):
    if not token:
        raise RuntimeError("GraphQL requires BACKUP_TOKEN, even for public projects.")
    payload = json.dumps({"query": query, "variables": variables}).encode()
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(
            f"{API}/graphql", data=payload,
            headers={**_headers(token), "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
            if "errors" in data and data["errors"]:
                msg = json.dumps(data["errors"])[:800]
                # graphql rate limit -> retry
                if "rate limit" in msg.lower() and attempt < retries - 1:
                    print("  GraphQL rate limit, waiting 60s...")
                    time.sleep(60)
                    continue
                raise RuntimeError(f"GraphQL errors: {msg}")
            return data["data"]
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            wait = _sleep_on_ratelimit(e.headers or {}, e.code)
            if wait is not None and attempt < retries - 1:
                print(f"  GraphQL {e.code}, waiting {wait}s...")
                time.sleep(wait)
                continue
            if e.code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"GraphQL HTTP {e.code}: {body}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"GraphQL failed after {retries} attempts: {last_err}")


def write_json(path: str | Path, data) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return p.stat().st_size
