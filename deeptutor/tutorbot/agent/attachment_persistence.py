"""Persist canonical Attachment objects to AttachmentStore in place.

Called from the agent loop before the multimodal/LLM step so the saved
session JSONL stores compact URL refs instead of inline base64. Mirrors
the legacy chat path at ``services/session/turn_runtime.py:752`` — we
don't share code because the call shapes differ (TutorBot deals with the
canonical ``Attachment`` dataclass; ``turn_runtime`` works with raw dicts
during a longer extraction pipeline).
"""

from __future__ import annotations

import base64 as _b64
import logging
import uuid

from deeptutor.core.context import Attachment
from deeptutor.services.storage import get_attachment_store

logger = logging.getLogger(__name__)


async def persist_attachments(
    session_id: str,
    attachments: list[Attachment],
) -> None:
    """Persist any attachment that has base64 bytes but no url.

    Mutates each Attachment: sets ``.url`` to the public URL and clears
    ``.base64`` once bytes are safely on disk. On failure, leaves
    ``base64`` intact so the LLM call can still proceed from the
    in-memory payload — the attachment just won't survive a page reload.
    """
    if not attachments:
        return
    store = get_attachment_store()
    for att in attachments:
        if att.url:
            continue  # already hosted
        if not att.base64:
            continue
        if not att.id:
            att.id = uuid.uuid4().hex[:12]
        try:
            raw = _b64.b64decode(att.base64, validate=False)
        except Exception as exc:
            logger.warning(
                "tutorbot: skipping attachment persistence for %r: bad base64 (%s)",
                att.filename, exc,
            )
            continue
        try:
            att.url = await store.put(
                session_id=session_id,
                attachment_id=att.id,
                filename=att.filename or "file",
                data=raw,
                mime_type=att.mime_type or "",
            )
            att.base64 = ""  # bytes live on disk; multimodal will read
                             # via _resolve_local_attachment_url
        except Exception as exc:
            logger.warning(
                "tutorbot: attachment store rejected %r: %s — keeping base64",
                att.filename, exc,
            )
