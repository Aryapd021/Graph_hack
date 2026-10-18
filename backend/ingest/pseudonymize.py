"""Pseudonymization helper for contributor identities.

Per ARCHITECTURE.md sections 2, 5, 6.1, 7:
- Decision D5: No personal data (emails, real names, avatars) is ever stored or exposed.
- Deterministic identity hashing:
    person_id = "p_" + sha256(PSEUDONYM_SALT + login)[:8]
    display = "Contributor " + those_8_hex_chars
"""

import hashlib


def pseudonymize_login(login: str, salt: str) -> tuple[str, str]:
    """Convert a raw GitHub login into a deterministic pseudonym ID and display name.

    Returns:
        tuple[str, str]: (person_id, display_name)
        Example: ('p_e4a7b9c2', 'Contributor e4a7b9c2')
    """
    # Why: Salt ensures hashes are specific to this deployment, preventing cross-correlation
    combined = salt + login
    digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:8]
    person_id = f"p_{digest}"
    display_name = f"Contributor {digest}"
    return person_id, display_name
