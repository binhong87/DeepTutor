import type { Metadata } from "next";
import { Plus_Jakarta_Sans, Lora } from "next/font/google";
import { AppShellProvider } from "@/context/AppShellContext";
import { AuthProvider } from "@/context/AuthContext";
import { TutorBotProvider } from "@/context/TutorBotContext";
import { I18nClientBridge } from "@/i18n";
import "./globals.css";

const jakartaSans = Plus_Jakarta_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
});

const lora = Lora({
  variable: "--font-serif",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "DeepTutor - TutorBot",
  description: "Personalized AI tutoring agents",
  icons: { icon: "/favicon.ico" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      data-scroll-behavior="smooth"
      className={`${jakartaSans.variable} ${lora.variable} h-full antialiased`}
    >
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("deeptutor-theme");if(!t||t==="system"){t=window.matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light"}var h=document.documentElement;h.classList.remove("dark","theme-glass","theme-snow");if(t==="dark")h.classList.add("dark");else if(t==="glass"){h.classList.add("dark","theme-glass")}else if(t==="snow")h.classList.add("theme-snow")}catch(e){}})()`,
          }}
        />
      </head>
      <body className="font-sans bg-[var(--background)] text-[var(--foreground)] min-h-full flex flex-col">
        <AppShellProvider>
          <AuthProvider>
            <TutorBotProvider>
              <I18nClientBridge>{children}</I18nClientBridge>
            </TutorBotProvider>
          </AuthProvider>
        </AppShellProvider>
      </body>
    </html>
  );
}
