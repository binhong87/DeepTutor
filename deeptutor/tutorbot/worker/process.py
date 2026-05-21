"""Worker process entrypoint — each TutorBot runs here in isolation."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def worker_main(bot_id: str, workspace: Path, redis_url: str, config: dict) -> None:
    """Entrypoint called by multiprocessing.Process. Runs its own event loop."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_async_main(bot_id, workspace, redis_url, config))


async def _async_main(bot_id: str, workspace: Path, redis_url: str, config: dict) -> None:
    from deeptutor.services.tutorbot.manager import BotConfig
    from deeptutor.services.tutorbot.model_runtime import resolve_tutorbot_llm_config
    from deeptutor.tutorbot.agent.loop import AgentLoop
    from deeptutor.tutorbot.bus.redis_bus import RedisMessageBus
    from deeptutor.tutorbot.config.schema import ExecToolConfig
    from deeptutor.tutorbot.providers.deeptutor_adapter import create_deeptutor_provider
    from deeptutor.tutorbot.session.manager import SessionManager

    stop_event = asyncio.Event()

    def _on_sigterm(*_: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, _on_sigterm)

    bus = RedisMessageBus(bot_id=bot_id, redis_url=redis_url)
    await bus.replay_pending()

    user_memory_dir_str = (config or {}).pop("_user_memory_dir", None)
    user_id = (config or {}).pop("_user_id", None)
    user_memory_dir = Path(user_memory_dir_str) if user_memory_dir_str else None
    bot_config = BotConfig(**config) if config else BotConfig(name=bot_id)
    llm_config = resolve_tutorbot_llm_config(bot_config)
    provider = create_deeptutor_provider(llm_config)
    session_adapter = SessionManager(workspace)
    venv_bin = str(Path(sys.executable).parent)
    exec_config = ExecToolConfig(timeout=300, path_append=venv_bin)

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=llm_config.model,
        context_window_tokens=llm_config.context_window or 65_536,
        exec_config=exec_config,
        session_manager=session_adapter,
        user_memory_dir=user_memory_dir,
        user_id=user_id,
        restrict_to_workspace=False,
        default_session_key=f"bot:{bot_id}",
    )

    loop_task = asyncio.create_task(agent_loop.run(), name=f"worker:{bot_id}:loop")
    stop_task = asyncio.create_task(stop_event.wait(), name=f"worker:{bot_id}:stop")

    await asyncio.wait([loop_task, stop_task], return_when=asyncio.FIRST_COMPLETED)

    agent_loop.stop()
    for task in [loop_task, stop_task]:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    await bus.close()
    logger.info("Worker for bot '%s' shut down cleanly", bot_id)
