"""Data models for the visualize pipeline."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class VisualizationAnalysis(BaseModel):
    """Output of the analysis stage."""

    render_type: Literal["svg", "chartjs", "mermaid", "html", "function_graph", "geometry"] = Field(
        description=(
            "Whether to render as raw SVG, a Chart.js configuration, a Mermaid "
            "diagram, a self-contained interactive HTML page, a function-plot graph "
            "(function_graph), or a JSXGraph geometry construction (geometry)."
        ),
    )
    description: str = Field(
        default="",
        description="High-level description of what the visualization should show.",
    )
    data_description: str = Field(
        default="",
        description="Description of the data or elements to be visualized.",
    )
    chart_type: str = Field(
        default="",
        description=(
            "Chart.js chart type (bar, line, pie, doughnut, radar, etc.) when render_type is chartjs, "
            "Mermaid diagram type (flowchart, sequenceDiagram, mindmap, classDiagram, stateDiagram, etc.) "
            "when render_type is mermaid, or a short interaction tag (e.g. 'interactive', 'animation', "
            "'walkthrough') when render_type is html."
        ),
    )
    visual_elements: list[str] = Field(
        default_factory=list,
        description="Key visual elements to include (shapes, labels, axes, colors, etc.).",
    )
    rationale: str = Field(
        default="",
        description="Why this render_type was chosen over the alternative.",
    )


# ── PlotSpec: the JSON contract for `mode=plot` (function_graph) ─────────────


class PlotFunction(BaseModel):
    """A single function to plot on the shared axes."""

    fn: str | dict[str, str] = Field(
        description=(
            "Expression in x (or parametric/polar object). "
            "Examples: 'sin(x)', 'x^2 - 1', "
            "{'x': 'cos(t)', 'y': 'sin(t)'} for parametric, "
            "{'r': '1 + cos(theta)'} for polar."
        ),
    )
    color: str | None = Field(default=None, description="CSS color, e.g. '#6366f1'.")
    label: str | None = Field(default=None, description="Legend label.")
    graphType: str | None = Field(
        default=None,
        description="'polyline' (default smooth curve), 'scatter', or 'interval'.",
    )

    @field_validator("graphType", mode="before")
    @classmethod
    def _coerce_graph_type(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = str(v).strip().lower()
        if v in {"polyline", "scatter", "interval"}:
            return v
        if v in {"line", "curve", ""}:
            return "polyline"
        if v == "points":
            return "scatter"
        return None


class PlotSpec(BaseModel):
    """Full JSON contract the LLM must emit for a `plot`."""

    title: str | None = None
    xDomain: tuple[float, float] = Field(description="[xMin, xMax] — required.")
    yDomain: tuple[float, float] | None = Field(
        default=None, description="[yMin, yMax] — omit to auto-scale."
    )
    xLabel: str | None = None
    yLabel: str | None = None
    functions: list[PlotFunction] = Field(
        min_length=1, description="One entry per curve; at least one required."
    )


# ── FigureSpec: the JSON contract for `mode=figure` (geometry) ───────────────


class FigureElement(BaseModel):
    """One element of the geometry construction.

    Loose on purpose — downstream validation (coord references, type-specific
    required fields) lives in the normaliser. We still reject obviously wrong
    shapes (no `type`, invalid top-level keys) here.
    """

    model_config = {"extra": "allow"}

    type: str = Field(description="point | segment | line | ray | circle | polygon | angle | arc | vector | text")


class FigureSpec(BaseModel):
    """Full JSON contract the LLM must emit for a `figure`."""

    title: str | None = None
    boundingBox: tuple[float, float, float, float] = Field(
        description="[xMin, yMax, xMax, yMin] — JSXGraph convention (top-left, bottom-right)."
    )
    elements: list[FigureElement] = Field(
        min_length=1,
        description="Construction elements in declaration order; later ones may reference earlier ids.",
    )


def validate_plot_spec(raw_json: Any) -> PlotSpec:
    """Return a parsed PlotSpec or raise ValidationError with a useful message."""
    return PlotSpec.model_validate(raw_json)


def validate_figure_spec(raw_json: Any) -> FigureSpec:
    """Return a parsed FigureSpec or raise ValidationError with a useful message."""
    return FigureSpec.model_validate(raw_json)
