import { AgentChatProvider } from "@/context/AgentChatContext";
import { V2Sidebar } from "@/components/agent/V2Sidebar";

export default function V2Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <AgentChatProvider>
      <div className="flex h-screen overflow-hidden">
        <V2Sidebar />
        <main className="flex-1 overflow-hidden bg-[var(--background)]">
          {children}
        </main>
      </div>
    </AgentChatProvider>
  );
}
