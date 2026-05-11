"use client";

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface GeometryElement {
  type: string;
  id?: string;
  coords?: [number, number];
  label?: string;
  color?: string;
  size?: number;
  from?: string | [number, number];
  to?: string | [number, number];
  center?: string | [number, number];
  radius?: number | string;
  vertices?: string[];
  vertex?: string;
  fillColor?: string;
  fillOpacity?: number;
  strokeWidth?: number;
  content?: string;
  fontSize?: number;
}

interface GeometrySpec {
  title?: string;
  boundingBox: [number, number, number, number];
  elements: GeometryElement[];
}

interface GeometryGraphProps {
  spec: string;
  className?: string;
}

let jxgModule: any | null = null;

async function loadJSXGraph() {
  if (!jxgModule) {
    jxgModule = await import("jsxgraph");
  }
  return jxgModule;
}

let geoIdCounter = 0;

export const GeometryGraph: React.FC<GeometryGraphProps> = ({
  spec,
  className = "",
}) => {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const [id] = useState(() => `geometry-graph-${++geoIdCounter}`);
  const boardRef = useRef<any>(null);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        const parsed: GeometrySpec = JSON.parse(spec);
        const mod = await loadJSXGraph();
        const JXG = mod.JXG ?? mod.default;
        if (cancelled) return;

        if (boardRef.current) {
          JXG.JSXGraph.freeBoard(boardRef.current);
          boardRef.current = null;
        }

        const board = JXG.JSXGraph.initBoard(id, {
          boundingbox: parsed.boundingBox,
          axis: true,
          showNavigation: false,
          showCopyright: false,
        });
        boardRef.current = board;

        const elemMap: Record<string, any> = {};

        function resolveRef(ref: string | [number, number] | undefined) {
          if (typeof ref === "string") return elemMap[ref];
          return ref;
        }

        for (const el of parsed.elements) {
          const attrs: Record<string, any> = {};
          if (el.label !== undefined) attrs.name = el.label;
          if (el.color) attrs.strokeColor = el.color;
          if (el.fillColor) attrs.fillColor = el.fillColor;
          if (el.fillOpacity !== undefined) attrs.fillOpacity = el.fillOpacity;
          if (el.strokeWidth !== undefined) attrs.strokeWidth = el.strokeWidth;
          if (el.size !== undefined) attrs.size = el.size;

          switch (el.type) {
            case "point": {
              const p = board.create("point", el.coords!, attrs);
              if (el.id) elemMap[el.id] = p;
              break;
            }
            case "segment":
              board.create(
                "segment",
                [resolveRef(el.from), resolveRef(el.to)],
                attrs,
              );
              break;
            case "line":
              board.create(
                "line",
                [resolveRef(el.from), resolveRef(el.to)],
                attrs,
              );
              break;
            case "ray":
              board.create("line", [resolveRef(el.from), resolveRef(el.to)], {
                ...attrs,
                straightFirst: false,
              });
              break;
            case "circle": {
              const radiusArg =
                typeof el.radius === "string" ? elemMap[el.radius] : el.radius;
              board.create(
                "circle",
                [resolveRef(el.center), radiusArg],
                attrs,
              );
              break;
            }
            case "polygon": {
              const verts = (el.vertices ?? []).map((v) => elemMap[v]);
              board.create("polygon", verts, attrs);
              break;
            }
            case "angle":
              board.create(
                "angle",
                [
                  elemMap[el.from as string],
                  elemMap[el.vertex!],
                  elemMap[el.to as string],
                ],
                attrs,
              );
              break;
            case "arc":
              board.create(
                "arc",
                [resolveRef(el.center), resolveRef(el.from), resolveRef(el.to)],
                attrs,
              );
              break;
            case "vector":
              board.create(
                "arrow",
                [resolveRef(el.from), resolveRef(el.to)],
                attrs,
              );
              break;
            case "text":
              if (el.fontSize) attrs.fontSize = el.fontSize;
              board.create("text", [...el.coords!, el.content ?? ""], attrs);
              break;
          }
        }

        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : t("Failed to render geometry"),
          );
        }
      }
    }

    void render();
    return () => {
      cancelled = true;
      if (boardRef.current && jxgModule) {
        const JXG = jxgModule.JXG ?? jxgModule.default;
        try {
          JXG.JSXGraph.freeBoard(boardRef.current);
        } catch {
          /* ignore */
        }
        boardRef.current = null;
      }
    };
  }, [spec, id, t]);

  if (error) {
    return (
      <div
        className={`my-4 p-4 bg-red-50 border border-red-200 rounded-lg ${className}`}
      >
        <p className="text-red-600 text-sm font-medium mb-2">
          {t("Geometry rendering error")}
        </p>
        <pre className="text-xs text-red-500 whitespace-pre-wrap">{error}</pre>
        <details className="mt-2">
          <summary className="text-xs text-[var(--muted-foreground)] cursor-pointer">
            {t("Show source")}
          </summary>
          <pre className="mt-2 p-2 bg-[var(--muted)] rounded text-xs overflow-x-auto text-[var(--foreground)]">
            {spec}
          </pre>
        </details>
      </div>
    );
  }

  return (
    <div
      id={id}
      className={`my-6 ${className}`}
      style={{ width: "100%", height: 500 }}
    />
  );
};

export default GeometryGraph;
