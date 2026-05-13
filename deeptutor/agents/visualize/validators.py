"""Server-side normalization and validation for plot/figure outputs.

The LLM frequently produces minor-but-fatal mistakes: `pi` vs `PI`, `Math.PI`,
`π`, trailing commas, etc. Normalise and validate once here so the frontend
renderers can trust what they receive, and so we can give the LLM a precise
error message when the schema is wrong (rather than a silent empty render).
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from .models import FigureSpec, PlotSpec


# ── Math expression normalisation ────────────────────────────────────────────

# function-plot's expression engine only recognises uppercase PI / E.
# LLMs routinely emit lowercase `pi`, `Math.PI`, or Greek `π`.
_PI_PATTERNS = [
    (re.compile(r"\bMath\.PI\b"), "PI"),
    (re.compile(r"π"), "PI"),
    (re.compile(r"\bpi\b"), "PI"),
]
_E_PATTERNS = [
    (re.compile(r"\bMath\.E\b"), "E"),
    # `e` alone is ambiguous (could be a variable name); only replace when
    # it is adjacent to a math operator / grouping char.
    (re.compile(r"\be\b(?=\s*[*/+\-^)])"), "E"),
    (re.compile(r"(?<=[*/+\-^(])\s*\be\b"), "E"),
]


def normalise_expression(expr: str) -> str:
    """Map common LLM aliases onto the symbols function-plot understands."""
    s = expr
    for pat, repl in _PI_PATTERNS:
        s = pat.sub(repl, s)
    for pat, repl in _E_PATTERNS:
        s = pat.sub(repl, s)
    return s


# ── Plot (function_graph) ────────────────────────────────────────────────────


def normalise_plot_json(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply cheap, mechanical fixes to a parsed plot JSON before validation."""
    if not isinstance(raw, dict):
        return raw
    # xDomain / yDomain sometimes arrive as list[int]; pydantic accepts both
    # but we coerce for uniformity.
    for key in ("xDomain", "yDomain"):
        if key in raw and isinstance(raw[key], list) and len(raw[key]) == 2:
            raw[key] = [float(raw[key][0]), float(raw[key][1])]

    functions = raw.get("functions")
    if isinstance(functions, list):
        for f in functions:
            if isinstance(f, dict):
                fn = f.get("fn")
                if isinstance(fn, str):
                    f["fn"] = normalise_expression(fn)
                elif isinstance(fn, dict):
                    for k in ("x", "y", "r"):
                        if isinstance(fn.get(k), str):
                            fn[k] = normalise_expression(fn[k])
    return raw


def validate_plot_code(code: str) -> str:
    """Parse + normalise + re-emit a plot JSON document. Raises on failure.

    Returns the cleaned JSON string, guaranteed to round-trip through PlotSpec.
    """
    raw = json.loads(code)
    raw = normalise_plot_json(raw)
    spec = PlotSpec.model_validate(raw)
    # Re-serialise with the normalised fields so the frontend gets canonical JSON.
    return json.dumps(spec.model_dump(exclude_none=True), ensure_ascii=False, indent=2)


# ── Figure (geometry) ────────────────────────────────────────────────────────

_ALLOWED_FIGURE_TYPES = {
    "point", "segment", "line", "ray", "circle",
    "polygon", "angle", "arc", "vector", "text",
}


def _figure_element_errors(elements: list[dict[str, Any]]) -> list[str]:
    """Cheap post-validation: known type, id referenced elements exist."""
    errors: list[str] = []
    seen_ids: set[str] = set()

    def _is_coord(v: Any) -> bool:
        return isinstance(v, list) and len(v) == 2 and all(
            isinstance(x, (int, float)) for x in v
        )

    for idx, el in enumerate(elements):
        t = el.get("type")
        if t not in _ALLOWED_FIGURE_TYPES:
            errors.append(f"element[{idx}]: unknown type {t!r}")
            continue

        el_id = el.get("id")
        if isinstance(el_id, str) and el_id:
            seen_ids.add(el_id)

        def _ref_ok(v: Any) -> bool:
            if isinstance(v, str):
                return v in seen_ids
            return _is_coord(v)

        if t == "point":
            if not _is_coord(el.get("coords")):
                errors.append(f"element[{idx}] (point): `coords` must be [x, y]")
        elif t in {"segment", "line", "ray", "vector"}:
            for side in ("from", "to"):
                if not _ref_ok(el.get(side)):
                    errors.append(
                        f"element[{idx}] ({t}): `{side}` must be an existing point id or [x, y]"
                    )
        elif t == "circle":
            if not _ref_ok(el.get("center")):
                errors.append(
                    f"element[{idx}] (circle): `center` must be an existing point id or [x, y]"
                )
            radius = el.get("radius")
            if not (isinstance(radius, (int, float)) or (isinstance(radius, str) and radius in seen_ids)):
                errors.append(
                    f"element[{idx}] (circle): `radius` must be a number or an existing point id"
                )
        elif t == "polygon":
            vertices = el.get("vertices")
            if not isinstance(vertices, list) or len(vertices) < 3:
                errors.append(f"element[{idx}] (polygon): `vertices` must be a list of ≥3 ids")
            else:
                for v in vertices:
                    if v not in seen_ids:
                        errors.append(
                            f"element[{idx}] (polygon): vertex {v!r} is not a declared point id"
                        )
        elif t == "angle":
            for side in ("vertex", "from", "to"):
                v = el.get(side)
                if not (isinstance(v, str) and v in seen_ids):
                    errors.append(
                        f"element[{idx}] (angle): `{side}` must be an existing point id"
                    )
        elif t == "arc":
            for side in ("center", "from", "to"):
                v = el.get(side)
                if not (isinstance(v, str) and v in seen_ids):
                    errors.append(
                        f"element[{idx}] (arc): `{side}` must be an existing point id"
                    )
        elif t == "text":
            if not _is_coord(el.get("coords")):
                errors.append(f"element[{idx}] (text): `coords` must be [x, y]")
            if not isinstance(el.get("content"), str):
                errors.append(f"element[{idx}] (text): `content` must be a string")

    return errors


def validate_figure_code(code: str) -> str:
    """Parse + validate a figure JSON document. Raises on failure.

    Returns the normalised JSON string.
    """
    raw = json.loads(code)
    spec = FigureSpec.model_validate(raw)
    # Extra referential checks — pydantic on FigureElement is permissive.
    errors = _figure_element_errors(
        [el.model_dump() if hasattr(el, "model_dump") else el for el in spec.elements]
    )
    if errors:
        raise ValidationError.from_exception_data(
            "FigureSpec",
            [{"type": "value_error", "loc": (), "msg": "; ".join(errors), "input": raw}],
        )
    return json.dumps(spec.model_dump(exclude_none=True), ensure_ascii=False, indent=2)


__all__ = [
    "normalise_expression",
    "normalise_plot_json",
    "validate_plot_code",
    "validate_figure_code",
]
