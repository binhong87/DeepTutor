"""Code generation stage: produce SVG or Chart.js code from the analysis."""

from __future__ import annotations

import json
import logging
import re

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id

from ..models import VisualizationAnalysis
from ..utils import extract_code_block

_log = logging.getLogger(__name__)
_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_FENCE_START_RE = re.compile(r"^```[A-Za-z_]*\s*\n")


class CodeGeneratorAgent(BaseAgent):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        language: str = "zh",
    ) -> None:
        super().__init__(
            module_name="visualize",
            agent_name="code_generator_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )

    async def process(
        self,
        *,
        user_input: str,
        history_context: str,
        analysis: VisualizationAnalysis,
    ) -> str:
        system_prompt = self.get_prompt("system")
        user_template = self.get_prompt("user_template")
        if not system_prompt or not user_template:
            raise ValueError("CodeGeneratorAgent prompts are not configured.")

        user_prompt = user_template.format(
            user_input=user_input.strip(),
            history_context=history_context.strip() or "(none)",
            render_type=analysis.render_type,
            analysis_json=json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2),
        )

        chunks: list[str] = []
        async for chunk in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            stage="generating",
            trace_meta=build_trace_metadata(
                call_id=new_call_id("viz-codegen"),
                phase="generating",
                label="Code generation",
                call_kind="viz_code_generation",
                trace_role="generate",
                trace_kind="llm_output",
            ),
        ):
            chunks.append(chunk)
        response = "".join(chunks)

        if analysis.render_type == "svg":
            lang_hint = "svg"
        elif analysis.render_type == "mermaid":
            lang_hint = "mermaid"
        elif analysis.render_type == "html":
            lang_hint = "html"
        elif analysis.render_type == "function_graph":
            lang_hint = "function_graph"
        elif analysis.render_type == "geometry":
            lang_hint = "geometry"
        else:
            lang_hint = "javascript"

        # Try to extract code block BEFORE stripping <think> blocks.
        # Some models embed the code inside <think>...</think>; stripping
        # first would discard the code entirely.
        extracted = extract_code_block(response, lang_hint) or extract_code_block(response)

        # Unwrap double-nested fences: reasoning models sometimes write ```html
        # inside a <think> block preview, causing the captured group to itself
        # start with ```html\n.  Re-extract from the captured group to get the
        # actual code inside.
        if extracted and _FENCE_START_RE.match(extracted):
            inner = extract_code_block(extracted, lang_hint) or extract_code_block(extracted)
            if inner and inner != extracted:
                extracted = inner

        # If extracted content contains <think> blocks, strip them now.
        if extracted and _THINK_RE.search(extracted):
            extracted = _THINK_RE.sub("", extracted).strip()

        # If extraction yielded nothing (or only the raw think-block text),
        # fall back to the stripped response and try again.
        if not extracted or extracted == response.strip():
            stripped_response = _THINK_RE.sub("", response).strip()
            if stripped_response:
                extracted = extract_code_block(stripped_response, lang_hint) or extract_code_block(stripped_response)
                if not extracted and stripped_response.lower().lstrip().startswith(("<!doctype", "<html")):
                    extracted = stripped_response

        _log.info(
            "code_generator: render_type=%s raw_len=%d extracted_len=%d",
            analysis.render_type,
            len(response),
            len(extracted) if extracted else 0,
        )

        return extracted
