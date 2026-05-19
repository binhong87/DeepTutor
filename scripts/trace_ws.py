#!/usr/bin/env python
"""Trace every WebSocket message for a tutorbot session."""
import asyncio
import io
import json
import sys
import time

# Force UTF-8 output on Windows (avoids GBK UnicodeEncodeError for emoji/CJK)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

import websockets

BOT_ID = sys.argv[1] if len(sys.argv) > 1 else "abc"
MESSAGE = sys.argv[2] if len(sys.argv) > 2 else "帮我画一张正弦函数的图像吧"
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 8001
WS_URL = f"ws://localhost:{PORT}/api/v1/tutorbot/{BOT_ID}/ws"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0MUBkZW1vLmNvbSIsInJvbGUiOiJhZG1pbiIsInVpZCI6InVfNzNmMGM2NzQ1Njc0NGJjNWFmM2QxMmNkODdlMTQyNjYiLCJleHAiOjE3Nzg4NDMyNTAsImlhdCI6MTc3ODc1Njg1MH0.4XhlSh4SlSNgIhVKtkLvRGrGZZSOUhYdoo8_opHG_4g"


def ts() -> str:
    return f"[{time.strftime('%H:%M:%S')}]"


async def main() -> None:
    print(f"{ts()} Connecting to {WS_URL}")
    headers = {
        "Cookie": f"dt_token={TOKEN}",
        "Authorization": f"Bearer {TOKEN}",
    }
    async with websockets.connect(WS_URL, additional_headers=headers) as ws:
        print(f"{ts()} Connected. Sending: {MESSAGE!r}")
        t0 = time.monotonic()
        await ws.send(json.dumps({"content": MESSAGE}))

        delta_count = 0
        non_delta_count = 0

        def rel() -> str:
            return f"+{time.monotonic() - t0:6.2f}s"

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=200)
            except asyncio.TimeoutError:
                print(f"{ts()} {rel()} TIMEOUT — no message in 200s")
                break
            except websockets.exceptions.ConnectionClosed as exc:
                print(f"{ts()} {rel()} Connection closed: {exc}")
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"{ts()} {rel()} RAW (non-JSON): {raw[:200]}")
                continue

            mtype = msg.get("type")
            content = msg.get("content", "")

            if mtype == "thinking":
                is_delta = bool(msg.get("delta"))
                tool_hint = bool(msg.get("tool_hint"))
                if is_delta:
                    delta_count += 1
                else:
                    non_delta_count += 1
                tag = "DELTA " if is_delta else ("HINT  " if tool_hint else "THINK ")
                preview = content[:120].replace("\n", "\\n")
                print(f"{ts()} {rel()} {tag}    | {preview}")
            elif mtype == "content":
                print(f"{ts()} {rel()} CONTENT   | len={len(content)}")
                print("----- content start -----")
                print(content[:3000])
                if len(content) > 3000:
                    print(f"... ({len(content) - 3000} more chars)")
                print("----- content end -----")
            elif mtype == "done":
                print(f"{ts()} {rel()} DONE      | deltas={delta_count} other_thinking={non_delta_count}")
                break
            elif mtype == "error":
                print(f"{ts()} {rel()} ERROR     | {content}")
                break
            elif mtype == "lesson_plan":
                plan = msg.get("plan", {})
                steps = plan.get("steps", [])
                cur = plan.get("current_step_id")
                summary = ", ".join(f"{s.get('id')}:{s.get('status', '?')}" for s in steps)
                print(f"{ts()} {rel()} PLAN      | topic={plan.get('topic')!r} current={cur} steps=[{summary}]")
            else:
                print(f"{ts()} {rel()} UNKNOWN   | type={mtype!r} content={str(content)[:120]}")


if __name__ == "__main__":
    asyncio.run(main())
