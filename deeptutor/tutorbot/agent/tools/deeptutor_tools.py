"""Adapter tools that expose DeepTutor capabilities as TutorBot function-calling tools."""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.tutorbot.agent.tools.base import Tool
from deeptutor.tutorbot.agent.tools.registry import DIRECT_RESULT_PREFIX as _DIRECT_RESULT_PREFIX

_log = logging.getLogger(__name__)


class BrainstormAdapterTool(Tool):
    @property
    def name(self) -> str:
        return "brainstorm"

    @property
    def description(self) -> str:
        return "Broadly explore multiple possibilities for a topic and give a short rationale for each."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic, goal, or problem to brainstorm about.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional supporting context, constraints, or background.",
                },
            },
            "required": ["topic"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from deeptutor.tools.brainstorm import brainstorm

        result = await brainstorm(
            topic=kwargs.get("topic", ""),
            context=kwargs.get("context", ""),
        )
        return result.get("answer", "")


class RAGAdapterTool(Tool):
    @property
    def name(self) -> str:
        return "rag"

    @property
    def description(self) -> str:
        return (
            "Search a knowledge base using Retrieval-Augmented Generation. "
            "Returns relevant passages and an LLM-synthesised answer."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "kb_name": {
                    "type": "string",
                    "description": "Knowledge base to search.",
                },
                "mode": {
                    "type": "string",
                    "description": "Search mode.",
                    "enum": ["naive", "local", "global", "hybrid"],
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from deeptutor.tools.rag_tool import rag_search

        result = await rag_search(
            query=kwargs.get("query", ""),
            kb_name=kwargs.get("kb_name"),
        )
        return result.get("answer") or result.get("content", "")


class CodeExecutionAdapterTool(Tool):
    _CODEGEN_SYSTEM_PROMPT = (
        "You are a Python code generator.\n"
        "Convert the user's natural-language request into executable Python code only.\n"
        "Rules:\n"
        "- Output only Python code, with no markdown fences or explanation.\n"
        "- Prefer standard library plus common packages: math, numpy, pandas, matplotlib, scipy, sympy.\n"
        "- Print the final answer to stdout.\n"
        "- Keep the code focused on the requested computation."
    )

    @property
    def name(self) -> str:
        return "code_execution"

    @property
    def description(self) -> str:
        return (
            "Turn a natural-language computation request into Python, "
            "run it in a sandboxed worker, and return the result."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "Natural-language description of the computation or verification task.",
                },
                "code": {
                    "type": "string",
                    "description": "Optional raw Python code to execute directly.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max execution time in seconds.",
                },
            },
            "required": ["intent"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from deeptutor.tools.code_executor import run_code

        code = str(kwargs.get("code") or "").strip()
        intent = str(kwargs.get("intent") or "").strip()
        timeout = int(kwargs.get("timeout", 30) or 30)

        if not code:
            if not intent:
                return "Error: code_execution requires either 'intent' or 'code'."
            code = await self._generate_code(intent)

        result = await run_code(language="python", code=code, timeout=timeout)
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        exit_code = result.get("exit_code", 1)

        parts: list[str] = []
        if stdout:
            parts.append(stdout.strip())
        if stderr:
            label = "Error" if exit_code else "Stderr"
            parts.append(f"{label}:\n{stderr.strip()}")
        return "\n\n".join(parts) if parts else "Execution completed with no output."

    async def _generate_code(self, intent: str) -> str:
        from deeptutor.services.llm import complete, get_token_limit_kwargs
        from deeptutor.services.llm.config import get_llm_config

        cfg = get_llm_config()
        extra: dict[str, Any] = {"temperature": 0.0}
        if cfg.model:
            extra.update(get_token_limit_kwargs(cfg.model, 1200))

        response = await complete(
            prompt=intent,
            system_prompt=self._CODEGEN_SYSTEM_PROMPT,
            model=cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            api_version=getattr(cfg, "api_version", None),
            binding=getattr(cfg, "binding", None),
            **extra,
        )
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            lines = lines[1:] if lines[0].startswith("```") else lines
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        if not cleaned:
            raise ValueError("LLM returned empty code for code_execution")
        return cleaned


class ReasonAdapterTool(Tool):
    @property
    def name(self) -> str:
        return "reason"

    @property
    def description(self) -> str:
        return (
            "Perform deep reasoning on a complex sub-problem using a dedicated LLM call. "
            "Use when the current context is insufficient for a confident answer."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The sub-problem to reason about.",
                },
                "context": {
                    "type": "string",
                    "description": "Supporting context for reasoning.",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from deeptutor.tools.reason import reason

        result = await reason(
            query=kwargs.get("query", ""),
            context=kwargs.get("context", ""),
        )
        return result.get("answer", "")


class PaperSearchAdapterTool(Tool):
    @property
    def name(self) -> str:
        return "paper_search"

    @property
    def description(self) -> str:
        return "Search arXiv preprints by keyword and return concise metadata."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum papers to return.",
                },
                "years_limit": {
                    "type": "integer",
                    "description": "Only include preprints from the last N years.",
                },
                "sort_by": {
                    "type": "string",
                    "description": "Sort by relevance or submission date.",
                    "enum": ["relevance", "date"],
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from deeptutor.tools.paper_search_tool import ArxivSearchTool

        papers = await ArxivSearchTool().search_papers(
            query=kwargs.get("query", ""),
            max_results=kwargs.get("max_results", 3),
            years_limit=kwargs.get("years_limit", 3),
            sort_by=kwargs.get("sort_by", "relevance"),
        )
        if not papers:
            return "No arXiv preprints found for this query."

        lines: list[str] = []
        for p in papers:
            lines.append(f"**{p['title']}** ({p.get('year', '?')})")
            lines.append(f"Authors: {', '.join(p.get('authors', []))}")
            lines.append(f"arXiv: {p.get('arxiv_id', '')}  URL: {p.get('url', '')}")
            lines.append(f"Abstract: {p.get('abstract', '')[:400]}")
            lines.append("")
        return "\n".join(lines)


class VisualizeAdapterTool(Tool):
    @property
    def name(self) -> str:
        return "visualize"

    @property
    def description(self) -> str:
        return (
            "**Render a visualization inline in the chat UI.** Use this for ANY chart, plot, "
            "function graph, diagram, or interactive visual the user asks to *see* — sine/cosine "
            "curves, bar/line/pie charts, geometry figures, flowcharts, etc. "
            "The returned fenced code block (html / svg / chartjs / mermaid / function_graph / "
            "geometry) is rendered directly in the chat as an iframe, SVG, or chart. "
            "**Do NOT use write_file for visualizations** — files on disk are invisible to the "
            "user. Always use this tool when the user wants to view a graphic."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "Natural-language description of the visualization to generate.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional conversation history or background context.",
                },
                "render_mode": {
                    "type": "string",
                    "description": (
                        "Render type. Use 'function_graph' for mathematical function plots "
                        "(sin, cos, polynomial, etc.). Use 'html' for charts, data plots, "
                        "and interactive visualizations. Use 'mermaid' for diagrams. "
                        "Defaults to 'html'."
                    ),
                    "enum": ["html", "function_graph", "mermaid", "chartjs", "geometry", "svg"],
                },
            },
            "required": ["request"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from deeptutor.agents.visualize.models import VisualizationAnalysis
        from deeptutor.agents.visualize.pipeline import VisualizePipeline
        from deeptutor.agents.visualize.utils import (
            build_fallback_html,
            is_valid_html_document,
        )
        from deeptutor.services.llm.config import get_llm_config

        cfg = get_llm_config()
        user_input = str(kwargs.get("request", "")).strip()
        history_context = str(kwargs.get("context", "") or "").strip()
        render_mode = str(kwargs.get("render_mode", "html") or "html").strip().lower()

        try:
            pipeline = VisualizePipeline(
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                api_version=cfg.api_version,
                language="en",
            )

            # Skip AnalysisAgent when render_mode is explicitly specified — saves one
            # slow LLM call (100-200 s on reasoning models). Build a minimal analysis
            # object directly from the forced render_mode instead.
            _NEEDS_ANALYSIS = {"auto"}
            if render_mode in _NEEDS_ANALYSIS:
                analysis = await pipeline.run_analysis(
                    user_input=user_input,
                    history_context=history_context,
                    render_mode=render_mode,
                )
            else:
                analysis = VisualizationAnalysis(
                    render_type=render_mode,  # type: ignore[arg-type]
                    description=user_input[:300],
                    data_description="",
                    chart_type="",
                    visual_elements=[],
                    rationale=f"render_mode forced to {render_mode}",
                )

            code = await pipeline.run_code_generation(
                user_input=user_input,
                history_context=history_context,
                analysis=analysis,
            )

            # Skip ReviewAgent for modes where a second LLM call rarely pays
            # off — html/function_graph/svg/geometry are typically simple
            # enough that review adds ~30–90s of latency for no quality gain,
            # and it's the single biggest contributor to timeouts on slow
            # reasoning models.
            _SKIP_REVIEW = {"html", "function_graph", "svg", "geometry"}
            if analysis.render_type == "html":
                if is_valid_html_document(code):
                    final_code = code
                else:
                    final_code = build_fallback_html(
                        title=analysis.description or "Visualization",
                        summary=analysis.data_description,
                        note="The model did not return a renderable HTML document.",
                    )
            elif analysis.render_type in _SKIP_REVIEW:
                final_code = code
            else:
                review = await pipeline.run_review(
                    user_input=user_input,
                    analysis=analysis,
                    code=code,
                )
                final_code = review.optimized_code

            lang_map = {
                "svg": "svg",
                "mermaid": "mermaid",
                "html": "html",
                "function_graph": "function_graph",
                "geometry": "geometry",
                "chartjs": "chartjs",
            }
            lang_tag = lang_map.get(analysis.render_type, "text")
            return f"{_DIRECT_RESULT_PREFIX}```{lang_tag}\n{final_code}\n```"
        except Exception:
            _log.exception("VisualizeAdapterTool.execute failed (render_mode=%r)", render_mode)
            raise
