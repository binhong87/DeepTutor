import AppSidebar from "@/components/ui/AppSidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <AppSidebar />
      <main className="flex-1 min-w-0">{children}</main>
    </div>
  );
}
