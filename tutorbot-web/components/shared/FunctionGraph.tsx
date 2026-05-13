"use client";

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface FunctionEntry {
  fn: string;
  color?: string;
  label?: string;
  graphType?: string;
}

interface FunctionSpec {
  title?: string;
  xDomain: [number, number];
  yDomain?: [number, number];
  xLabel?: string;
  yLabel?: string;
  functions: FunctionEntry[];
}

interface FunctionGraphProps {
  spec: string;
  className?: string;
}

let fpLoader: Promise<any> | null = null;

async function loadFunctionPlot() {
  if (!fpLoader) {
    fpLoader = import("function-plot").then((m) => m.default ?? m);
  }
  return fpLoader;
}

let fpIdCounter = 0;

/**
 * function-plot's expression engine only recognises a small set of constant
 * symbols (uppercase `PI`, `E`). LLMs however routinely emit lowercase `pi`,
 * `Math.PI`, or Greek `π`. Normalise those before handing the expression off
 * so we do not fail on well-formed math.
 */
function normalizeFnExpression(fn: string): string {
  return fn
    .replace(/\bMath\.PI\b/g, "PI")
    .replace(/\bMath\.E\b/g, "E")
    .replace(/π/g, "PI")
    .replace(/\bpi\b/g, "PI")
    .replace(/\be\b(?=\s*[*/+\-^)])/g, "E");
}

export const FunctionGraph: React.FC<FunctionGraphProps> = ({
  spec,
  className = "",
}) => {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [id] = useState(() => `function-graph-${++fpIdCounter}`);

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;

    async function render() {
      try {
        const parsed: FunctionSpec = JSON.parse(spec);
        const functionPlot = await loadFunctionPlot();
        if (cancelled || !containerRef.current) return;

        containerRef.current.innerHTML = "";

        const options: Record<string, unknown> = {
          target: containerRef.current,
          width: containerRef.current.offsetWidth || 500,
          height: 350,
          xAxis: { domain: parsed.xDomain, label: parsed.xLabel },
          yAxis: parsed.yDomain
            ? { domain: parsed.yDomain, label: parsed.yLabel }
            : { label: parsed.yLabel },
          data: parsed.functions.map((f) => ({
            fn: normalizeFnExpression(f.fn),
            ...(f.color && { color: f.color }),
            ...(f.graphType && { graphType: f.graphType }),
          })),
          grid: true,
        };

        if (parsed.title) options.title = parsed.title;

        functionPlot(options);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : t("Failed to render graph"),
          );
        }
      }
    }

    void render();
    return () => {
      cancelled = true;
    };
  }, [spec, id, t]);

  if (error) {
    return (
      <div
        className={`my-4 p-4 bg-red-50 border border-red-200 rounded-lg ${className}`}
      >
        <p className="text-red-600 text-sm font-medium mb-2">
          {t("Graph rendering error")}
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
      ref={containerRef}
      id={id}
      className={`my-6 overflow-x-auto ${className}`}
      style={{ width: "100%", minHeight: 350 }}
    />
  );
};

export default FunctionGraph;
