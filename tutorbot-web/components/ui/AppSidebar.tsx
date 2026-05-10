"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, BookOpen, LayoutGrid, LogOut, PanelLeftClose, PanelLeftOpen, Settings } from "lucide-react";
import { useAppShell } from "@/context/AppShellContext";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/tutorbot/dashboard", label: "TutorBot", icon: Bot },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/tutorbot/souls", label: "Souls", icon: LayoutGrid },
];

export default function AppSidebar() {
  const pathname = usePathname();
  const { sidebarCollapsed, setSidebarCollapsed } = useAppShell();
  const { isAuthenticated, logout, isAdmin } = useAuth();

  return (
    <aside
      className={cn(
        "flex flex-col border-r border-[var(--border)] bg-[var(--card)] h-screen sticky top-0 transition-all duration-200",
        sidebarCollapsed ? "w-[60px]" : "w-[220px]",
      )}
    >
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--border)]">
        {!sidebarCollapsed && (
          <Link href="/tutorbot/dashboard" className="text-sm font-semibold text-[var(--foreground)] truncate">
            DeepTutor
          </Link>
        )}
        <button
          onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          className={cn("p-1 rounded-md hover:bg-[var(--muted)] text-[var(--muted-foreground)]", sidebarCollapsed && "mx-auto")}
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {sidebarCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </button>
      </div>

      <nav className="flex-1 py-3 px-2 space-y-1">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-[var(--primary)]/10 text-[var(--primary)] font-medium"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]",
                sidebarCollapsed && "justify-center px-2",
              )}
              title={sidebarCollapsed ? label : undefined}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!sidebarCollapsed && <span className="truncate">{label}</span>}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-[var(--border)] px-2 py-3 space-y-1">
        {isAdmin && (
          <Link
            href="/settings"
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] transition-colors",
              sidebarCollapsed && "justify-center px-2",
            )}
            title={sidebarCollapsed ? "Settings" : undefined}
          >
            <Settings className="h-4 w-4 shrink-0" />
            {!sidebarCollapsed && <span>Settings</span>}
          </Link>
        )}
        {isAuthenticated && (
          <button
            onClick={logout}
            className={cn(
              "w-full flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] transition-colors",
              sidebarCollapsed && "justify-center px-2",
            )}
            title={sidebarCollapsed ? "Sign out" : undefined}
          >
            <LogOut className="h-4 w-4 shrink-0" />
            {!sidebarCollapsed && <span>Sign out</span>}
          </button>
        )}
      </div>
    </aside>
  );
}
