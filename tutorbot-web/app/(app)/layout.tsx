import AppSidebar from "@/components/ui/AppSidebar";
import LanguageSwitcher from "@/components/ui/LanguageSwitcher";
import { SessionTreeProvider } from "@/context/SessionTreeContext";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionTreeProvider>
      <div className="flex h-screen overflow-hidden">
        <AppSidebar />
        <main className="relative flex-1 min-w-0 overflow-y-auto">
          <LanguageSwitcher className="fixed top-3 right-4 z-50" />
          {children}
        </main>
      </div>
    </SessionTreeProvider>
  );
}
