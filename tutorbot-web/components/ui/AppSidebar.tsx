"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import {
  Archive,
  BookOpen,
  Bot,
  ChevronDown,
  ChevronRight,
  LayoutGrid,
  LogOut,
  Menu,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  User,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAppShell } from "@/context/AppShellContext";
import { useAuth } from "@/context/AuthContext";
import { useSessionTree } from "@/context/SessionTreeContext";
import { createBotSession, type BotTreeRow, type SessionRow } from "@/lib/tutorbot-api";
import { cn } from "@/lib/utils";

export default function AppSidebar() {
  const pathname = usePathname();
  const { sidebarCollapsed, setSidebarCollapsed } = useAppShell();
  const [isMobile, setIsMobile] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { isAuthenticated, logout } = useAuth();
  const { t } = useTranslation();

  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 768);
    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDrawerOpen(false);
  }, [pathname]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!isMobile) setDrawerOpen(false);
  }, [isMobile]);

  const { tree, expanded, toggleBot, refresh } = useSessionTree();
  const router = useRouter();
  const { sessionId: routeSessionId, botId: routeBotId } = useParams<{
    sessionId?: string;
    botId?: string;
  }>();

  async function onNewChatClick(
    botId: string,
    defaultId: string,
    defaultIsEmpty: boolean,
  ) {
    if (defaultIsEmpty) {
      router.push(`/tutorbot/${botId}/chat/${defaultId}`);
      return;
    }
    try {
      const newDefault = await createBotSession(botId);
      await refresh();
      router.push(`/tutorbot/${botId}/chat/${newDefault.id}`);
    } catch (e) {
      const err = e as { code?: number; data?: { existing_default_id?: string } };
      if (err.code === 409) {
        const existing = err.data?.existing_default_id;
        await refresh();
        if (existing) router.push(`/tutorbot/${botId}/chat/${existing}`);
      }
    }
  }

  return (
    <>
      {isMobile && !drawerOpen && (
        <button
          onClick={() => setDrawerOpen(true)}
          className="fixed top-3 left-3 z-50 p-1.5 rounded-md bg-[var(--card)] border border-[var(--border)] text-[var(--foreground)] shadow-sm"
          aria-label={t("Open menu")}
        >
          <Menu className="h-5 w-5" />
        </button>
      )}
      {isMobile && drawerOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30"
          onClick={() => setDrawerOpen(false)}
          aria-hidden="true"
        />
      )}
      <aside
        className={cn(
          "flex flex-col border-r border-[var(--border)] bg-[var(--card)] h-screen sticky top-0 transition-all duration-200",
          sidebarCollapsed ? "w-[60px]" : "w-[260px]",
        )}
      >
        <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--border)]">
          {!sidebarCollapsed && (
            <Link
              href="/tutorbot/dashboard"
              className="text-sm font-semibold text-[var(--foreground)] truncate"
            >
              DeepTutor
            </Link>
          )}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className={cn(
              "p-1 rounded-md hover:bg-[var(--muted)] text-[var(--muted-foreground)]",
              sidebarCollapsed && "mx-auto",
            )}
            aria-label={sidebarCollapsed ? t("Expand sidebar") : t("Collapse sidebar")}
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen className="h-4 w-4" />
            ) : (
              <PanelLeftClose className="h-4 w-4" />
            )}
          </button>
        </div>

        <nav className="flex-1 py-3 px-2 space-y-1 overflow-y-auto">
          {sidebarCollapsed ? (
            <CollapsedNav pathname={pathname} t={t} />
          ) : (
            <>
              <Link
                href="/tutorbot/dashboard"
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                  pathname.startsWith("/tutorbot/dashboard")
                    ? "bg-[var(--primary)]/10 text-[var(--primary)] font-medium"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]",
                )}
              >
                <Bot className="h-4 w-4 shrink-0" />
                <span className="truncate">{t("TutorBot")}</span>
              </Link>

              {tree.length > 0 && (
                <div className="pt-1">
                  {tree.map((bot) => {
                    const isExpanded = expanded[bot.bot_id] ?? bot.bot_id === routeBotId;
                    const defaultRow = bot.sessions.find((s) => s.status === "default");
                    const defaultIsEmpty = !!defaultRow && !defaultRow.has_user_messages;
                    return (
                      <div key={bot.bot_id} className="ml-2">
                        <div
                          className="group flex items-center gap-1 px-2 py-1.5 text-[13px] rounded-md hover:bg-[var(--muted)] cursor-pointer"
                          onClick={() => toggleBot(bot.bot_id)}
                        >
                          <span className="text-[var(--muted-foreground)]">
                            {isExpanded ? (
                              <ChevronDown className="h-3 w-3" />
                            ) : (
                              <ChevronRight className="h-3 w-3" />
                            )}
                          </span>
                          <Bot className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
                          <span className="flex-1 truncate text-[var(--foreground)]">
                            {bot.name}
                          </span>
                          {bot.running && (
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                          )}
                          {defaultRow && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                void onNewChatClick(bot.bot_id, defaultRow.id, defaultIsEmpty);
                              }}
                              disabled={defaultIsEmpty}
                              className="opacity-0 group-hover:opacity-100 disabled:opacity-20 disabled:cursor-not-allowed text-[var(--muted-foreground)] hover:text-[var(--foreground)] rounded p-0.5"
                              title={t("New chat")}
                              aria-label={t("New chat")}
                            >
                              <Plus className="h-3 w-3" />
                            </button>
                          )}
                        </div>
                        {isExpanded && bot.sessions.length > 0 && (
                          <div className="ml-4 border-l border-[var(--border)] pl-2 space-y-0.5 py-0.5">
                            {bot.sessions.map((s) => (
                              <SessionRowView
                                key={s.id}
                                bot={bot}
                                session={s}
                                active={s.id === routeSessionId}
                              />
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              <div className="pt-2">
                <Link
                  href="/knowledge"
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                    pathname.startsWith("/knowledge")
                      ? "bg-[var(--primary)]/10 text-[var(--primary)] font-medium"
                      : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]",
                  )}
                >
                  <BookOpen className="h-4 w-4 shrink-0" />
                  <span className="truncate">{t("Knowledge")}</span>
                </Link>
                <Link
                  href="/tutorbot/souls"
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                    pathname.startsWith("/tutorbot/souls")
                      ? "bg-[var(--primary)]/10 text-[var(--primary)] font-medium"
                      : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]",
                  )}
                >
                  <LayoutGrid className="h-4 w-4 shrink-0" />
                  <span className="truncate">{t("Souls")}</span>
                </Link>
              </div>
            </>
          )}
        </nav>

        <div className="border-t border-[var(--border)] px-2 py-3 space-y-1">
          {isAuthenticated && (
            <Link
              href="/profile"
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] transition-colors",
                sidebarCollapsed && "justify-center px-2",
              )}
              title={sidebarCollapsed ? t("Profile") : undefined}
            >
              <User className="h-4 w-4 shrink-0" />
              {!sidebarCollapsed && <span>{t("Profile")}</span>}
            </Link>
          )}
          {isAuthenticated && (
            <button
              onClick={logout}
              className={cn(
                "w-full flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] transition-colors",
                sidebarCollapsed && "justify-center px-2",
              )}
              title={sidebarCollapsed ? t("Sign out") : undefined}
            >
              <LogOut className="h-4 w-4 shrink-0" />
              {!sidebarCollapsed && <span>{t("Sign out")}</span>}
            </button>
          )}
        </div>
      </aside>
    </>
  );
}

function SessionRowView({
  bot,
  session,
  active,
}: {
  bot: BotTreeRow;
  session: SessionRow;
  active: boolean;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const fallbackTitle =
    session.status === "archived" ? t("Previous chat") : t("New chat");
  const title = session.title || fallbackTitle;
  const Icon =
    session.status === "archived" ? Archive : session.status === "default" ? Plus : MessageSquare;
  const brief = session.lesson_plan_brief;

  return (
    <button
      onClick={() => router.push(`/tutorbot/${bot.bot_id}/chat/${session.id}`)}
      className={cn(
        "group w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-[12.5px] text-left transition-colors",
        active
          ? "bg-[var(--primary)]/10 text-[var(--primary)] font-medium"
          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]",
        session.status === "default" && "italic",
      )}
      title={title}
    >
      <Icon className="h-3 w-3 shrink-0" />
      <span className="flex-1 truncate">{title}</span>
      {session.status === "active" && brief && brief.total_steps > 0 && (
        <span className="text-[10px] text-[var(--muted-foreground)] group-hover:text-[var(--foreground)]">
          {brief.done_steps}/{brief.total_steps}
        </span>
      )}
      {session.status === "completed" && (
        <span className="text-[10px] px-1.5 py-px rounded bg-[var(--muted)] text-[var(--muted-foreground)]">
          {t("Done")}
        </span>
      )}
      {session.status === "archived" && (
        <span className="text-[10px] px-1.5 py-px rounded bg-[var(--muted)] text-[var(--muted-foreground)]">
          {t("Archived")}
        </span>
      )}
    </button>
  );
}

function CollapsedNav({
  pathname,
  t,
}: {
  pathname: string;
  t: (k: string) => string;
}) {
  const items = [
    { href: "/tutorbot/dashboard", label: t("TutorBot"), icon: Bot },
    { href: "/knowledge", label: t("Knowledge"), icon: BookOpen },
    { href: "/tutorbot/souls", label: t("Souls"), icon: LayoutGrid },
  ];
  return (
    <>
      {items.map(({ href, label, icon: Icon }) => {
        const active = pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center justify-center rounded-lg px-2 py-2 text-sm transition-colors",
              active
                ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]",
            )}
            title={label}
          >
            <Icon className="h-4 w-4 shrink-0" />
          </Link>
        );
      })}
    </>
  );
}
