"""
Capa 1 — Pull GitHub Copilot governance signals into Application Insights.

What it pulls
-------------
1. Audit log events with `action:copilot.*` (who did what, when, from which
   repo). REQUIRES: GitHub Enterprise Cloud OR Enterprise-managed org +
   token with `read:audit_log`.
2. Copilot usage metrics (daily aggregates: chats, suggestions, acceptance
   rate, breakdown by language/editor). REQUIRES: token with
   `manage_billing:copilot` or `read:enterprise`.
3. Copilot seat assignments (who has a license, last activity).

What it CANNOT pull
-------------------
- Content of prompts / responses (GitHub does not expose it).
- Per-turn model id or tokens (only daily aggregates).
- → For that you need Capa 2 (APIM AI Gateway) or Capa 4 (extension).

How to run
----------
Required env vars:
    GITHUB_TOKEN                        Personal Access Token or GitHub App
                                        installation token. Scopes:
                                        - read:audit_log
                                        - manage_billing:copilot OR read:enterprise
    GITHUB_ENTERPRISE   (optional)      Slug, e.g. "example". Pulls enterprise scope.
    GITHUB_ORG          (optional)      Slug, e.g. "my-org". Pulls org scope.
                                        At least one of ENTERPRISE/ORG must be set.

    APPLICATIONINSIGHTS_CONNECTION_STRING
                                        Where to emit events. If unset → dry-run.

Optional env vars:
    COPILOT_AUDIT_CURSOR_FILE           Path to cursor JSON.
                                        Default: scenario-3/.copilot-audit-cursor.json
    COPILOT_AUDIT_MAX_PAGES             Safety cap. Default 50.
    COPILOT_AUDIT_LOOKBACK_DAYS         First-run lookback. Default 7.

Commands
--------
    python copilot_audit_pull.py audit       # pulls audit log events
    python copilot_audit_pull.py usage       # pulls usage metrics
    python copilot_audit_pull.py seats       # pulls seat assignments
    python copilot_audit_pull.py all         # pulls everything (cron use case)
    python copilot_audit_pull.py --dry-run all
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

# Ensure ``scenario-3/src`` is importable so we can reuse telemetry.configure
_TOOLS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TOOLS_DIR.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scenario-3" / "src"))

from opentelemetry import trace  # noqa: E402

import telemetry as corp_telemetry  # noqa: E402

GITHUB_API = "https://api.github.com"
USER_AGENT = "agent-eval-poc/copilot-audit-pull"
DEFAULT_CURSOR_FILE = _REPO_ROOT / "scenario-3" / ".copilot-audit-cursor.json"


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only — keeps the tool dep-light for CI)
# ---------------------------------------------------------------------------


class GitHubError(RuntimeError):
    """Raised when GitHub returns a non-2xx response that we can't recover from."""


def _request(
    path: str,
    *,
    token: str,
    params: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, str]]:
    """GET helper that returns (json_body, headers_dict)."""
    url = f"{GITHUB_API}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        },
    )
    # Tiny backoff on 5xx + abuse.
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8") or "null"
                return json.loads(body), dict(resp.headers)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 3:
                sleep = int(e.headers.get("Retry-After", "5"))
                print(
                    f"[copilot-audit] {e.code} on {url} — sleeping {sleep}s",
                    file=sys.stderr,
                )
                time.sleep(sleep)
                continue
            if 500 <= e.code < 600 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            detail = e.read().decode("utf-8", "replace")[:500] if e.fp else ""
            raise GitHubError(f"{e.code} {e.reason}: {url}\n{detail}") from e
    raise GitHubError(f"giving up on {url} after retries")


def _paginate(
    path: str,
    *,
    token: str,
    params: dict[str, Any] | None = None,
    max_pages: int = 50,
) -> Iterator[list[dict]]:
    """Yields each page (list of items) until exhausted or max_pages."""
    next_url: str | None = None
    page_no = 0
    while page_no < max_pages:
        if next_url is None:
            body, headers = _request(path, token=token, params=params)
        else:
            # next_url is absolute, strip the base for _request
            parsed = urllib.parse.urlparse(next_url)
            sub = parsed.path + ("?" + parsed.query if parsed.query else "")
            body, headers = _request(sub, token=token)

        if isinstance(body, list):
            yield body
        elif isinstance(body, dict) and "value" in body:
            yield body["value"]
        else:
            yield [body] if body else []

        page_no += 1
        link = headers.get("Link") or headers.get("link") or ""
        next_url = _next_link(link)
        if not next_url:
            return


def _next_link(link_header: str) -> str | None:
    for chunk in link_header.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            url_part, rel_part = chunk.split(";", 1)
        except ValueError:
            continue
        if 'rel="next"' in rel_part:
            return url_part.strip().lstrip("<").rstrip(">")
    return None


# ---------------------------------------------------------------------------
# Cursor (so re-runs are incremental)
# ---------------------------------------------------------------------------


def _load_cursor(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return {}


def _save_cursor(path: Path, cursor: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cursor, indent=2, sort_keys=True), "utf-8")


# ---------------------------------------------------------------------------
# Emit helpers — one span per event so App Insights groups them naturally.
# ---------------------------------------------------------------------------


def _emit_event(name: str, attrs: dict[str, Any], *, dry_run: bool) -> None:
    """Emit a single zero-duration span — shows up as a customEvent."""
    if dry_run:
        line = json.dumps({"name": name, "attrs": attrs}, default=str)
        print(line)
        return
    tracer = trace.get_tracer("corp.copilot.audit")
    with tracer.start_as_current_span(name) as span:
        for k, v in attrs.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                span.set_attribute(k, v)
            else:
                span.set_attribute(k, json.dumps(v, default=str))


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def _scope_prefix(enterprise: str | None, org: str | None) -> tuple[str, str]:
    """Returns ("enterprise"|"org", "<scope_path>")."""
    if enterprise:
        return ("enterprise", f"/enterprises/{enterprise}")
    if org:
        return ("org", f"/orgs/{org}")
    raise SystemExit(
        "Set GITHUB_ENTERPRISE or GITHUB_ORG so the tool knows what to query."
    )


def pull_audit_log(
    *,
    token: str,
    enterprise: str | None,
    org: str | None,
    cursor: dict[str, Any],
    max_pages: int,
    lookback_days: int,
    dry_run: bool,
) -> int:
    scope_kind, scope = _scope_prefix(enterprise, org)
    scope_key = f"audit:{scope_kind}:{enterprise or org}"

    last_doc_id = cursor.get(scope_key, {}).get("last_document_id")
    since = cursor.get(scope_key, {}).get("last_created_at")
    if not since:
        since = (
            datetime.now(timezone.utc) - timedelta(days=lookback_days)
        ).isoformat(timespec="seconds")

    params = {
        "phrase": f"action:copilot created:>={since}",
        "per_page": 100,
        "order": "asc",
    }

    seen = 0
    new_last_id: str | None = last_doc_id
    new_last_at: str | None = since
    try:
        for page in _paginate(
            f"{scope}/audit-log",
            token=token,
            params=params,
            max_pages=max_pages,
        ):
            for ev in page:
                # GitHub returns _document_id ; skip anything we've seen.
                doc_id = ev.get("_document_id") or ev.get("document_id")
                if last_doc_id and doc_id == last_doc_id:
                    continue
                attrs = {
                    "github.scope": scope_kind,
                    "github.scope_name": enterprise or org,
                    "github.action": ev.get("action"),
                    "github.actor": ev.get("actor"),
                    "github.actor_id": ev.get("actor_id"),
                    "github.user": ev.get("user"),
                    "github.repo": ev.get("repo") or ev.get("repository"),
                    "github.org": ev.get("org"),
                    "github.team": ev.get("team"),
                    "github.created_at": ev.get("created_at"),
                    "copilot.feature": ev.get("copilot_feature"),
                    "copilot.event": ev.get("action"),
                    "copilot.document_id": doc_id,
                    "copilot.raw": ev,  # full event, JSON-stringified
                }
                _emit_event("copilot.audit.event", attrs, dry_run=dry_run)
                seen += 1
                new_last_id = doc_id or new_last_id
                if ev.get("created_at"):
                    new_last_at = ev["created_at"]
    except GitHubError as e:
        # 404 on /enterprises means you don't have the right plan; degrade.
        print(f"[copilot-audit] audit log unavailable: {e}", file=sys.stderr)
        return 0

    cursor[scope_key] = {
        "last_document_id": new_last_id,
        "last_created_at": new_last_at,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return seen


# ---------------------------------------------------------------------------
# Usage metrics (daily)
# ---------------------------------------------------------------------------


def pull_usage(
    *,
    token: str,
    enterprise: str | None,
    org: str | None,
    cursor: dict[str, Any],
    dry_run: bool,
) -> int:
    scope_kind, scope = _scope_prefix(enterprise, org)
    scope_key = f"usage:{scope_kind}:{enterprise or org}"
    last_day = cursor.get(scope_key, {}).get("last_day")

    try:
        body, _ = _request(f"{scope}/copilot/usage", token=token)
    except GitHubError as e:
        print(f"[copilot-audit] usage unavailable: {e}", file=sys.stderr)
        return 0

    if not isinstance(body, list):
        body = body.get("usage", []) if isinstance(body, dict) else []

    seen = 0
    new_last_day = last_day
    for day in body:
        date = day.get("day")
        if last_day and date and date <= last_day:
            continue
        attrs = {
            "github.scope": scope_kind,
            "github.scope_name": enterprise or org,
            "copilot.day": date,
            "copilot.total_suggestions": day.get("total_suggestions_count"),
            "copilot.total_acceptances": day.get("total_acceptances_count"),
            "copilot.total_lines_suggested": day.get("total_lines_suggested"),
            "copilot.total_lines_accepted": day.get("total_lines_accepted"),
            "copilot.total_active_users": day.get("total_active_users"),
            "copilot.total_chat_acceptances": day.get("total_chat_acceptances"),
            "copilot.total_chat_turns": day.get("total_chat_turns"),
            "copilot.total_active_chat_users": day.get("total_active_chat_users"),
            "copilot.breakdown": day.get("breakdown"),
        }
        _emit_event("copilot.usage.daily", attrs, dry_run=dry_run)
        seen += 1
        if date and (not new_last_day or date > new_last_day):
            new_last_day = date

    cursor[scope_key] = {
        "last_day": new_last_day,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return seen


# ---------------------------------------------------------------------------
# Seats
# ---------------------------------------------------------------------------


def pull_seats(
    *,
    token: str,
    enterprise: str | None,
    org: str | None,
    dry_run: bool,
    max_pages: int,
) -> int:
    scope_kind, scope = _scope_prefix(enterprise, org)
    seen = 0
    try:
        for page in _paginate(
            f"{scope}/copilot/billing/seats",
            token=token,
            params={"per_page": 100},
            max_pages=max_pages,
        ):
            # Endpoint returns {"total_seats": N, "seats": [...]}; we treat
            # both shapes by digging into "seats" if present.
            seats = page
            if len(page) == 1 and isinstance(page[0], dict) and "seats" in page[0]:
                seats = page[0]["seats"]
            for seat in seats:
                assignee = seat.get("assignee") or {}
                attrs = {
                    "github.scope": scope_kind,
                    "github.scope_name": enterprise or org,
                    "copilot.seat_id": seat.get("assignee_id"),
                    "copilot.assignee": assignee.get("login"),
                    "copilot.assignee_type": assignee.get("type"),
                    "copilot.assignee_id": assignee.get("id"),
                    "copilot.assigning_team": (
                        (seat.get("assigning_team") or {}).get("slug")
                    ),
                    "copilot.last_activity_at": seat.get("last_activity_at"),
                    "copilot.last_activity_editor": seat.get(
                        "last_activity_editor"
                    ),
                    "copilot.plan_type": seat.get("plan_type"),
                    "copilot.pending_cancellation_date": seat.get(
                        "pending_cancellation_date"
                    ),
                    "copilot.created_at": seat.get("created_at"),
                    "copilot.updated_at": seat.get("updated_at"),
                }
                _emit_event("copilot.seat.snapshot", attrs, dry_run=dry_run)
                seen += 1
    except GitHubError as e:
        print(f"[copilot-audit] seats unavailable: {e}", file=sys.stderr)
    return seen


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "kind",
        choices=("audit", "usage", "seats", "all"),
        help="Which signal to pull.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print events as JSON instead of emitting to App Insights.",
    )
    args = parser.parse_args(argv)

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("[copilot-audit] GITHUB_TOKEN is required", file=sys.stderr)
        return 2

    enterprise = os.getenv("GITHUB_ENTERPRISE") or None
    org = os.getenv("GITHUB_ORG") or None
    cursor_path = Path(
        os.getenv("COPILOT_AUDIT_CURSOR_FILE", str(DEFAULT_CURSOR_FILE))
    )
    max_pages = int(os.getenv("COPILOT_AUDIT_MAX_PAGES", "50"))
    lookback_days = int(os.getenv("COPILOT_AUDIT_LOOKBACK_DAYS", "7"))

    if not args.dry_run:
        if not os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
            print(
                "[copilot-audit] APPLICATIONINSIGHTS_CONNECTION_STRING not set "
                "— either export it or pass --dry-run",
                file=sys.stderr,
            )
            return 2
        corp_telemetry.configure(service_name="copilot-audit-pull")

    cursor = _load_cursor(cursor_path)
    total = 0
    if args.kind in ("audit", "all"):
        n = pull_audit_log(
            token=token,
            enterprise=enterprise,
            org=org,
            cursor=cursor,
            max_pages=max_pages,
            lookback_days=lookback_days,
            dry_run=args.dry_run,
        )
        print(f"[copilot-audit] audit events emitted: {n}", file=sys.stderr)
        total += n
    if args.kind in ("usage", "all"):
        n = pull_usage(
            token=token,
            enterprise=enterprise,
            org=org,
            cursor=cursor,
            dry_run=args.dry_run,
        )
        print(f"[copilot-audit] usage days emitted: {n}", file=sys.stderr)
        total += n
    if args.kind in ("seats", "all"):
        n = pull_seats(
            token=token,
            enterprise=enterprise,
            org=org,
            max_pages=max_pages,
            dry_run=args.dry_run,
        )
        print(f"[copilot-audit] seat snapshots emitted: {n}", file=sys.stderr)
        total += n

    if not args.dry_run:
        _save_cursor(cursor_path, cursor)
    print(f"[copilot-audit] DONE total={total}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
