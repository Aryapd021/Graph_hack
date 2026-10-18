"""GitHub REST data fetcher and processor.

Per ARCHITECTURE.md sections 5, 7:
- Uses httpx and optional GITHUB_TOKEN (warns if missing).
- Endpoints: pulls, pull files, git trees, contents, commits.
- Handles pagination, rate limit sleeping (403/429), and retry of 5xx errors.
- Filtering: merged PRs only; skip bots (SKIP_BOT_PRS); drop files matching no MODULE_RULES;
  skip PR if no kept files remain; MAX_PRS counts kept PRs only.
- Docs: DOC_PATH_PREFIXES, DOC_EXCLUDE, even spacing up to MAX_DOCS; kind; title; updated_at.
- Module of a file: first matching prefix + depth directory segments.
- Scrubbing and in-memory PII leak scans before saving to cache.
"""

import base64
import datetime
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from brain_core.config import IngestSettings, ModuleRule, get_ingest_settings
from ingest.pseudonymize import pseudonymize_login
from ingest.scrub import scan_for_logins, scan_for_pii, scrub_text


def resolve_module_path(file_path: str, module_rules: List[ModuleRule]) -> Optional[str]:
    """Determine module directory path from file path using first matching MODULE_RULES entry.

    Rules from Section 7:
    - First matching prefix wins.
    - Module path = prefix + next `depth` directory segments of path (excluding file name).
    - If file is directly inside prefix, module path = prefix with trailing slash stripped.
    """
    for rule in module_rules:
        prefix = rule.prefix  # e.g. "fastapi/" or "docs/en/docs/"
        depth = rule.depth    # e.g. 1
        if file_path.startswith(prefix):
            remainder = file_path[len(prefix):]
            # Directory segments before the file name
            parts = [p for p in remainder.split("/")[:-1] if p]
            selected = parts[:depth]
            if selected:
                mod_path = prefix + "/".join(selected)
            else:
                mod_path = prefix.rstrip("/")
            return mod_path.rstrip("/")
    return None


class GitHubFetcher:
    """Fetches, scrubs, and caches public GitHub repository data."""

    def __init__(self, settings: Optional[IngestSettings] = None):
        """Initialize the GitHub fetcher with ingestion configuration."""
        self.settings = settings or get_ingest_settings()
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "CompanyBrain-Ingest/0.1",
        }
        if self.settings.GITHUB_TOKEN:
            self.headers["Authorization"] = f"Bearer {self.settings.GITHUB_TOKEN}"
        else:
            # Why: Section 7 warns if GITHUB_TOKEN is omitted to alert user of 60 req/hr limits
            print("WARNING: GITHUB_TOKEN is unset. GitHub API requests will be limited to 60 req/hr.", file=sys.stderr)

        self.client = httpx.Client(headers=self.headers, timeout=30.0)
        self.author_logins: Set[str] = set()

    def _request(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Execute an HTTP request with automatic rate-limit waiting and 5xx retries."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = self.client.get(url, params=params)
                # Handle expired or invalid token gracefully
                if resp.status_code == 401 and "Authorization" in self.client.headers:
                    print(
                        "WARNING: GITHUB_TOKEN returned 401 Bad credentials. "
                        "Falling back to unauthenticated requests.",
                        file=sys.stderr,
                    )
                    del self.client.headers["Authorization"]
                    resp = self.client.get(url, params=params)

                # Handle rate limiting per Section 7
                if resp.status_code in (403, 429):
                    remaining = resp.headers.get("x-ratelimit-remaining")
                    if remaining == "0" or "rate limit" in resp.text.lower():
                        reset_header = resp.headers.get("x-ratelimit-reset")
                        current_time = time.time()
                        reset_time = float(reset_header) if reset_header else current_time + 60
                        wait_seconds = max(reset_time - current_time + 2, 2)
                        print(f"GitHub rate limit reached. Sleeping {wait_seconds:.1f}s until reset...", file=sys.stderr)
                        time.sleep(wait_seconds)
                        continue

                # Handle transient 5xx server errors
                if resp.status_code >= 500:
                    time.sleep(2 * (attempt + 1))
                    continue

                resp.raise_for_status()
                return resp.json()
            except httpx.RequestError as exc:
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 * (attempt + 1))

        raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts")

    def fetch_default_branch(self) -> str:
        """Fetch repository details to resolve the default branch."""
        repo = self.settings.GITHUB_REPO
        url = f"https://api.github.com/repos/{repo}"
        data = self._request(url)
        return data.get("default_branch", "main")

    def fetch_prs(self) -> List[Dict[str, Any]]:
        """Fetch merged pull requests and their modified files per Section 7."""
        repo = self.settings.GITHUB_REPO
        max_prs = self.settings.MAX_PRS
        skip_bots = self.settings.SKIP_BOT_PRS
        salt = self.settings.PSEUDONYM_SALT

        kept_prs: List[Dict[str, Any]] = []
        page = 1

        print(f"Fetching merged PRs for {repo} (target: {max_prs} kept PRs)...", flush=True)

        while len(kept_prs) < max_prs:
            url = f"https://api.github.com/repos/{repo}/pulls"
            params = {
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": 100,
                "page": page,
            }
            items = self._request(url, params=params)
            if not items:
                break

            for pr in items:
                # 1. Keep only merged PRs
                merged_at_str = pr.get("merged_at")
                if not merged_at_str:
                    continue

                # 2. Check bot exclusion
                user = pr.get("user") or {}
                user_type = user.get("type", "")
                raw_login = user.get("login", "")

                if skip_bots:
                    if user_type == "Bot" or raw_login.lower().endswith("[bot]"):
                        continue

                # Track author login in-memory for scrubbing and verification scan
                if raw_login:
                    self.author_logins.add(raw_login)

                pr_number = pr["number"]

                # 3. Fetch PR files
                files_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
                file_items = self._request(files_url, params={"per_page": 100})
                if not file_items:
                    continue

                # 4. Filter files by MODULE_RULES
                kept_files = []
                for f in file_items:
                    file_path = f.get("filename", "")
                    if resolve_module_path(file_path, self.settings.MODULE_RULES) is not None:
                        kept_files.append(file_path)

                # Skip PR entirely if no kept files remain
                if not kept_files:
                    continue

                # Convert timestamps to epoch integer
                created_at = int(
                    datetime.datetime.fromisoformat(
                        pr["created_at"].replace("Z", "+00:00")
                    ).timestamp()
                )
                merged_at = int(
                    datetime.datetime.fromisoformat(
                        merged_at_str.replace("Z", "+00:00")
                    ).timestamp()
                )

                # Pseudonymize author
                author_id, _ = pseudonymize_login(raw_login, salt)

                # Body excerpt up to 500 chars (will be scrubbed)
                raw_body = pr.get("body") or ""
                body_excerpt = raw_body[:500]
                raw_title = pr.get("title") or f"PR {pr_number}"

                kept_prs.append(
                    {
                        "number": pr_number,
                        "raw_title": raw_title,
                        "raw_body_excerpt": body_excerpt,
                        "created_at": created_at,
                        "merged_at": merged_at,
                        "author_id": author_id,
                        "url": f"https://github.com/{repo}/pull/{pr_number}",
                        "files": kept_files,
                    }
                )

                if len(kept_prs) >= max_prs:
                    break

            page += 1

        print(f"Retrieved {len(kept_prs)} merged PRs touching target modules.", flush=True)
        return kept_prs

    def fetch_docs(self, default_branch: str) -> List[Dict[str, Any]]:
        """Fetch and sample markdown documentation files per Section 7."""
        repo = self.settings.GITHUB_REPO
        max_docs = self.settings.MAX_DOCS
        max_doc_chars = self.settings.MAX_DOC_CHARS

        prefixes = [p.strip() for p in self.settings.DOC_PATH_PREFIXES.split(",") if p.strip()]
        excludes = [e.strip().lower() for e in self.settings.DOC_EXCLUDE.split(",") if e.strip()]

        print(f"Fetching repository tree for docs on branch '{default_branch}'...", flush=True)
        tree_url = f"https://api.github.com/repos/{repo}/git/trees/{default_branch}"
        tree_data = self._request(tree_url, params={"recursive": "1"})

        candidates = []
        for item in tree_data.get("tree", []):
            if item.get("type") != "blob":
                continue
            path = item.get("path", "")
            if not path.endswith(".md"):
                continue

            # Candidate rule: repo root README.md OR path starts with any DOC_PATH_PREFIXES
            is_candidate = (path == "README.md") or any(path.startswith(pref) for pref in prefixes)
            if not is_candidate:
                continue

            # Exclude rule: drop if path contains any DOC_EXCLUDE substring (case-insensitive)
            lower_path = path.lower()
            if path != "README.md" and any(exc in lower_path for exc in excludes):
                continue

            candidates.append(path)

        # Sort candidates deterministically by path
        candidates.sort()

        # Even spacing sampling if count > MAX_DOCS, always retaining README.md
        selected_paths: List[str] = []
        if len(candidates) > max_docs:
            step = math.ceil(len(candidates) / max_docs)
            sampled = candidates[::step]
            selected_paths = sampled[:max_docs]
            if "README.md" in candidates and "README.md" not in selected_paths:
                selected_paths[0] = "README.md"
        else:
            selected_paths = candidates

        print(f"Selected {len(selected_paths)} documentation files to fetch.", flush=True)

        docs: List[Dict[str, Any]] = []
        for path in selected_paths:
            # 1. Fetch file content
            content_url = f"https://api.github.com/repos/{repo}/contents/{path}"
            content_data = self._request(content_url)
            raw_content = ""
            if content_data.get("encoding") == "base64" and content_data.get("content"):
                raw_content = base64.b64decode(content_data["content"]).decode("utf-8", errors="replace")

            # 2. Fetch last change commit date
            commit_url = f"https://api.github.com/repos/{repo}/commits"
            commits = self._request(commit_url, params={"path": path, "per_page": 1})
            updated_at = int(time.time())
            if commits and isinstance(commits, list):
                commit_date_str = (
                    commits[0].get("commit", {}).get("committer", {}).get("date")
                )
                if commit_date_str:
                    updated_at = int(
                        datetime.datetime.fromisoformat(
                            commit_date_str.replace("Z", "+00:00")
                        ).timestamp()
                    )

            # 3. Determine kind per Section 7
            lower_p = path.lower()
            if "adr" in lower_p:
                kind = "adr"
            elif "design" in lower_p or "architecture" in lower_p:
                kind = "design"
            elif path.endswith("README.md"):
                kind = "readme"
            else:
                kind = "guide"

            # 4. Extract title: first H1 else file name
            title = Path(path).stem
            for line in raw_content.splitlines():
                stripped = line.strip()
                if stripped.startswith("# "):
                    title = stripped[2:].strip()
                    break

            # Truncate raw body to MAX_DOC_CHARS
            truncated_body = raw_content[:max_doc_chars]

            docs.append(
                {
                    "path": path,
                    "raw_title": title,
                    "kind": kind,
                    "updated_at": updated_at,
                    "raw_body": truncated_body,
                    "url": f"https://github.com/{repo}/blob/{default_branch}/{path}",
                }
            )

        return docs

    def run_fetch(self, cache_dir: Path, refresh: bool = False) -> None:
        """Execute full fetch pipeline, scrub all text, verify zero PII, and write cache."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        repo_cache = cache_dir / "repo.json"
        prs_cache = cache_dir / "prs.json"
        docs_cache = cache_dir / "docs.json"

        # Check if cache exists and not refreshing
        if not refresh and repo_cache.exists() and prs_cache.exists() and docs_cache.exists():
            print("Cached GitHub data exists. Skipping fetch (use --refresh to refetch).", flush=True)
            return

        # 1. Fetch repo info
        default_branch = self.fetch_default_branch()

        # 2. Fetch PRs and docs
        raw_prs = self.fetch_prs()
        raw_docs = self.fetch_docs(default_branch)

        print("Scrubbing PII and author logins from fetched text...", flush=True)

        # 3. Scrub PRs
        scrubbed_prs = []
        for item in raw_prs:
            title = scrub_text(item["raw_title"], self.author_logins)
            body_excerpt = scrub_text(item["raw_body_excerpt"], self.author_logins)
            scrubbed_prs.append(
                {
                    "number": item["number"],
                    "title": title,
                    "body_excerpt": body_excerpt,
                    "created_at": item["created_at"],
                    "merged_at": item["merged_at"],
                    "author_id": item["author_id"],
                    "url": item["url"],
                    "files": item["files"],
                }
            )

        # 4. Scrub Docs
        scrubbed_docs = []
        for item in raw_docs:
            title = scrub_text(item["raw_title"], self.author_logins)
            body = scrub_text(item["raw_body"], self.author_logins)
            scrubbed_docs.append(
                {
                    "path": item["path"],
                    "title": title,
                    "kind": item["kind"],
                    "updated_at": item["updated_at"],
                    "body": body,
                    "url": item["url"],
                }
            )

        # 5. PII Verification Scan
        print("Running in-memory PII verification scan...", flush=True)
        violations = []

        for pr in scrubbed_prs:
            violations.extend(scan_for_pii(pr["title"]))
            violations.extend(scan_for_pii(pr["body_excerpt"]))
            violations.extend(scan_for_logins(pr["title"], self.author_logins))
            violations.extend(scan_for_logins(pr["body_excerpt"], self.author_logins))

        for doc in scrubbed_docs:
            violations.extend(scan_for_pii(doc["title"]))
            violations.extend(scan_for_pii(doc["body"]))
            violations.extend(scan_for_logins(doc["title"], self.author_logins))
            violations.extend(scan_for_logins(doc["body"], self.author_logins))

        if violations:
            first_violations = violations[:5]
            raise ValueError(
                f"PII Verification Scan FAILED! Violations detected:\n"
                + "\n".join(f"  - {v}" for v in first_violations)
            )

        print("PII scan PASSED: Zero emails, mentions, profile URLs, or raw logins detected.", flush=True)

        # 6. Save cache files
        repo_info = {
            "repo": self.settings.GITHUB_REPO,
            "default_branch": default_branch,
            "fetched_at": int(time.time()),
        }

        repo_cache.write_text(json.dumps(repo_info, indent=2), encoding="utf-8")
        prs_cache.write_text(json.dumps(scrubbed_prs, indent=2), encoding="utf-8")
        docs_cache.write_text(json.dumps(scrubbed_docs, indent=2), encoding="utf-8")

        print(f"Saved {len(scrubbed_prs)} PRs and {len(scrubbed_docs)} docs to {cache_dir}", flush=True)
