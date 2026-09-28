#!/usr/bin/env python3
"""Back up roadmap = org-level Project V2 (stdlib only).
Usage:
  BACKUP_TOKEN=xxx python3 scripts/backup_roadmap.py --out backup
  # quick test: python3 scripts/backup_roadmap.py --out /tmp/bk --max-items 20
NOTE: GraphQL always requires a token, even for public projects.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_token, graphql, write_json
from config import ORG, PROJECT_NUMBER

FIELDS_Q = """
query($org: String!, $num: Int!, $fcursor: String) {
  organization(login: $org) {
    projectV2(number: $num) {
      id title number url closed closedAt createdAt updatedAt
      fields(first: 100, after: $fcursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          __typename
          ... on ProjectV2FieldCommon { id name dataType }
          ... on ProjectV2SingleSelectField { options { id name } }
          ... on ProjectV2IterationField {
            configuration {
              duration startDay
              iterations { id title startDate duration }
              completedIterations { id title startDate duration }
            }
          }
        }
      }
    }
  }
}
"""

ITEMS_Q = """
query($org: String!, $num: Int!, $cursor: String) {
  organization(login: $org) {
    projectV2(number: $num) {
      items(first: 100, after: $cursor) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes {
          id isArchived
          content {
            __typename
            ... on Issue { number title state url repository { nameWithOwner } labels(first: 20) { nodes { name } } assignees(first: 10) { nodes { login } } }
            ... on PullRequest { number title state url repository { nameWithOwner } }
            ... on DraftIssue { title body }
          }
          fieldValues(first: 50) {
            nodes {
              __typename
              ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldNumberValue { number field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldIterationValue {
                title startDate duration
                iterationId field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldMilestoneValue {
                milestone { title dueOn }
                field { ... on ProjectV2FieldCommon { name } }
              }
            }
          }
        }
      }
    }
  }
}
"""


def run(org: str, number: int, out: str, token: str | None,
        max_items: int = 0) -> dict:
    print(f"[roadmap] org={org} project=#{number} ...")
    if not token:
        raise SystemExit("BACKUP_TOKEN is required for GraphQL (even public projects). Export it and retry.")
    # fields (paginated, usually a single page is enough)
    fields, fcur = [], None
    while True:
        d = graphql(FIELDS_Q, {"org": org, "num": number, "fcursor": fcur}, token)
        pv = d["organization"]["projectV2"]
        if pv is None:
            raise SystemExit(f"project {org}/{number} not found or not readable with the given token.")
        fields.extend(pv["fields"]["nodes"])
        if not pv["fields"]["pageInfo"]["hasNextPage"]:
            meta = {k: pv.get(k) for k in ("id", "title", "number", "url", "closed", "closedAt", "createdAt", "updatedAt")}
            break
        fcur = pv["fields"]["pageInfo"]["endCursor"]

    # paginated items (100/page -> 10 calls per 1000 items, ~500 for 50k)
    items, cur, total = [], None, None
    page = 0
    while True:
        page += 1
        d = graphql(ITEMS_Q, {"org": org, "num": number, "cursor": cur}, token)
        conn = d["organization"]["projectV2"]["items"]
        total = conn["totalCount"]
        items.extend(conn["nodes"])
        print(f"  ... page {page}: {len(conn['nodes'])} items (total {len(items)}/{total})")
        if max_items and len(items) >= max_items:
            items = items[:max_items]
            print(f"  test mode: limited to {max_items} items")
            break
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cur = conn["pageInfo"]["endCursor"]
        if page > 600:  # safety cap at 60k items
            print("  safety stop at 600 pages")
            break

    payload = {"project": meta, "org": org, "fields": fields,
               "items": items, "fetched": len(items), "totalCount": total}
    size = write_json(Path(out) / "roadmap.json", payload)
    print(f"  {len(items)}/{total} items + {len(fields)} fields -> {out}/roadmap.json ({size/1024:.1f} KB)")
    return {"count": len(items), "total": total, "bytes": size}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="backup")
    ap.add_argument("--token", default=None)
    ap.add_argument("--max-items", type=int, default=0, help="0 = all, N = first N only (tests)")
    a = ap.parse_args()
    run(ORG, PROJECT_NUMBER, a.out, get_token(a.token), max_items=a.max_items)


if __name__ == "__main__":
    main()
