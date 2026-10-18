"""PII scrubbing and verification scans.

Per ARCHITECTURE.md section 7:
- Emails replaced with '[email]'
- @handle replaced with '@contributor'
- Lines starting with 'Co-authored-by:' or 'Signed-off-by:' deleted
- GitHub profile URLs (github.com/<single segment>) replaced with '[profile]'
- Known author logins replaced with 'contributor' (case-insensitive whole word)
- PII scan helper to verify zero leakage in text properties and caches
"""

import re
from typing import Iterable, Set

# Regex patterns for scrubbing
EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)
MENTION_REGEX = re.compile(r"@[A-Za-z0-9_-]+")
PROFILE_URL_REGEX = re.compile(
    r"https?://(?:www\.)?github\.com/[A-Za-z0-9_-]+/?(?=[^\w/-]|$)"
)
GIT_TRAILER_LINE_REGEX = re.compile(
    r"^[ \t]*(?:co-authored-by|signed-off-by):.*$", re.IGNORECASE | re.MULTILINE
)


def scrub_text(text: str, author_logins: Iterable[str] = ()) -> str:
    """Scrub sensitive PII from text before persistence.

    Why: Hackathon data policy and Decision D5 strictly prohibit storing personal
    identifying details, emails, or personal GitHub profile links.
    """
    if not text:
        return ""

    # 1. Delete lines starting with Co-authored-by: or Signed-off-by:
    result = GIT_TRAILER_LINE_REGEX.sub("", text)

    # 2. Replace GitHub user profile URLs (e.g. github.com/username) with [profile]
    # Note: repo/PR URLs like github.com/owner/repo/pull/123 are preserved
    result = PROFILE_URL_REGEX.sub("[profile]", result)

    # 3. Replace email addresses with [email]
    result = EMAIL_REGEX.sub("[email]", result)

    # 4. Replace @handle mentions with @contributor
    result = MENTION_REGEX.sub("@contributor", result)

    # 5. Replace known author logins with 'contributor'
    for login in author_logins:
        cleaned_login = login.strip()
        if cleaned_login:
            # Case-insensitive whole word replacement
            pattern = re.compile(r"\b" + re.escape(cleaned_login) + r"\b", re.IGNORECASE)
            result = pattern.sub("contributor", result)

    # Clean up empty lines created by stripped trailers
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result


def scan_for_pii(text: str) -> list[str]:
    """Scan text for any residual PII pattern classes.

    Returns a list of violation descriptions (empty if clean).
    """
    violations = []
    if not text:
        return violations

    # Check for unscrubbed emails
    emails = EMAIL_REGEX.findall(text)
    if emails:
        violations.append(f"Unscrubbed email detected: {emails[:3]}")

    # Check for unscrubbed mentions (excluding @contributor)
    for mention in MENTION_REGEX.findall(text):
        if mention != "@contributor":
            violations.append(f"Unscrubbed @mention detected: {mention}")
            break

    # Check for unscrubbed profile URLs
    profiles = PROFILE_URL_REGEX.findall(text)
    if profiles:
        violations.append(f"Unscrubbed profile URL detected: {profiles[:3]}")

    # Check for trailer lines
    trailers = GIT_TRAILER_LINE_REGEX.findall(text)
    if trailers:
        violations.append(f"Unscrubbed git trailer line detected: {trailers[:2]}")

    return violations


def scan_for_logins(text: str, author_logins: Set[str]) -> list[str]:
    """Scan text against known author logins to ensure none remain."""
    violations = []
    if not text or not author_logins:
        return violations

    for login in author_logins:
        if not login.strip():
            continue
        # Check whole word match
        pattern = re.compile(r"\b" + re.escape(login.strip()) + r"\b", re.IGNORECASE)
        if pattern.search(text):
            violations.append(f"Residual author login detected: {login}")

    return violations
