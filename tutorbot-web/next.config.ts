import type { NextConfig } from "next";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

function parseEnvFile(filePath: string): Record<string, string> {
  try {
    const content = readFileSync(filePath, "utf-8");
    const result: Record<string, string> = {};
    for (const line of content.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eqIdx = trimmed.indexOf("=");
      if (eqIdx === -1) continue;
      const key = trimmed.slice(0, eqIdx).trim();
      let value = trimmed.slice(eqIdx + 1).trim();
      if ((value.startsWith("\"") && value.endsWith("\"")) || (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      result[key] = value;
    }
    return result;
  } catch {
    return {};
  }
}

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const rootEnv = parseEnvFile(resolve(projectRoot, ".env"));

const BACKEND_PORT = rootEnv.BACKEND_PORT || "8001";

const NEXT_PUBLIC_API_BASE =
  rootEnv.NEXT_PUBLIC_API_BASE_EXTERNAL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  `http://localhost:${BACKEND_PORT}`;

let APP_VERSION = "dev";
try {
  APP_VERSION = execSync("git describe --tags --always --dirty=-dev", { cwd: projectRoot })
    .toString().trim();
} catch {
  // not a git repo or no tags
}

const AUTH_ENABLED = rootEnv.AUTH_ENABLED === "true";

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_APP_VERSION: APP_VERSION,
    NEXT_PUBLIC_API_BASE,
    NEXT_PUBLIC_AUTH_ENABLED: String(AUTH_ENABLED),
  },
  output: "standalone",
  transpilePackages: ["mermaid"],
  turbopack: {
    root: __dirname,
    resolveAlias: {
      cytoscape: "cytoscape/dist/cytoscape.cjs.js",
    },
  },
  // Dev-only HTTP proxy so the page can be HTTPS (required for mic / camera
  // on LAN origins) while uvicorn stays plain-HTTP. lib/api.ts resolveBase()
  // routes API requests same-origin when window.location is https:, which
  // funnels them through this rewrite. WebSocket upgrades aren't proxied —
  // chat-over-HTTPS still needs a real reverse proxy or HTTPS on uvicorn.
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    return [
      {
        source: "/api/:path*",
        destination: `http://localhost:${BACKEND_PORT}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
