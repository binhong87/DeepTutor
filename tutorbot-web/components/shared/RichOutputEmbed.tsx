"use client";

import type { RichOutputType } from "@/lib/agent-chat-types";

interface RichOutputEmbedProps {
  richOutputType: RichOutputType;
  richOutputData: unknown;
  sessionId: string | null;
  turnId: string;
}

// TutorBot chat does not produce quiz/math_animator/visualize/deep_research outputs.
// The viewer components live only in the main web/ app — keep this as a stub so
// AgentMessage.tsx can import it without conditional branches.
export function RichOutputEmbed(_props: RichOutputEmbedProps) {
  return null;
}
