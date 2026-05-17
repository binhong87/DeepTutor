"""Session id helpers.

DEFAULT_SID is the bootstrap-only well-known id for the very first default
session of a bot. After promotion, defaults get fresh ids from
new_session_id() — ids are immutable for the life of the session.
"""

from __future__ import annotations

import secrets

DEFAULT_SID = "s_default"


def new_session_id() -> str:
    """Return a short URL-safe random id, prefixed `s_`."""
    return "s_" + secrets.token_hex(6)
