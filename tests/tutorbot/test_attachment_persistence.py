"""Tests for tutorbot attachment persistence helper."""

import base64 as _b64
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.core.context import Attachment


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.put = AsyncMock(return_value="/api/attachments/sid/aid/voice.png")
    with patch(
        "deeptutor.tutorbot.agent.attachment_persistence.get_attachment_store",
        return_value=store,
    ):
        yield store


@pytest.mark.asyncio
async def test_persist_round_trip(mock_store):
    from deeptutor.tutorbot.agent.attachment_persistence import persist_attachments

    att = Attachment(
        type="image",
        base64=_b64.b64encode(b"\x89PNG\r\n\x1a\n").decode(),
        mime_type="image/png",
        filename="x.png",
        id="aid123",
    )
    await persist_attachments("sid", [att])
    assert att.url == "/api/attachments/sid/aid/voice.png"
    assert att.base64 == ""
    mock_store.put.assert_awaited_once()
    call_kwargs = mock_store.put.await_args.kwargs
    assert call_kwargs["session_id"] == "sid"
    assert call_kwargs["attachment_id"] == "aid123"
    assert call_kwargs["filename"] == "x.png"
    assert call_kwargs["mime_type"] == "image/png"
    assert call_kwargs["data"] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_already_hosted_skipped(mock_store):
    from deeptutor.tutorbot.agent.attachment_persistence import persist_attachments

    att = Attachment(
        type="image",
        url="/api/attachments/pre/existing/x.png",
        base64="should-be-ignored",
        mime_type="image/png",
        filename="x.png",
    )
    await persist_attachments("sid", [att])
    assert att.url == "/api/attachments/pre/existing/x.png"  # unchanged
    assert att.base64 == "should-be-ignored"  # not touched
    mock_store.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_base64_no_op(mock_store):
    from deeptutor.tutorbot.agent.attachment_persistence import persist_attachments

    att = Attachment(type="image", base64="", mime_type="image/png", filename="x.png")
    await persist_attachments("sid", [att])
    assert att.url == ""
    mock_store.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_assigns_id_when_missing(mock_store):
    from deeptutor.tutorbot.agent.attachment_persistence import persist_attachments

    att = Attachment(
        type="image",
        base64=_b64.b64encode(b"x").decode(),
        mime_type="image/png",
        filename="x.png",
        id="",
    )
    await persist_attachments("sid", [att])
    assert att.id  # got assigned
    assert len(att.id) == 12  # 12-char uuid hex


@pytest.mark.asyncio
async def test_store_failure_keeps_base64(mock_store):
    from deeptutor.tutorbot.agent.attachment_persistence import persist_attachments

    mock_store.put.side_effect = OSError("disk full")
    orig_b64 = _b64.b64encode(b"data").decode()
    att = Attachment(type="image", base64=orig_b64, mime_type="image/png", filename="x.png")
    await persist_attachments("sid", [att])  # must not raise
    assert att.url == ""  # not set
    assert att.base64 == orig_b64  # preserved for LLM call


@pytest.mark.asyncio
async def test_invalid_base64_logged_and_skipped(mock_store, caplog):
    from deeptutor.tutorbot.agent.attachment_persistence import persist_attachments

    att = Attachment(
        type="image",
        base64="!!!not-base64!!!" + "\x00\x01",  # contains non-base64 bytes
        mime_type="image/png",
        filename="x.png",
    )
    # b64decode with validate=False is permissive, so we need to force a
    # decode error. Patch b64decode to raise.
    with patch(
        "deeptutor.tutorbot.agent.attachment_persistence._b64.b64decode",
        side_effect=ValueError("invalid base64"),
    ):
        await persist_attachments("sid", [att])
    assert att.url == ""
    mock_store.put.assert_not_awaited()
