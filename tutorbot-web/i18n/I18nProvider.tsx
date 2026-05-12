"use client";

import { useEffect } from "react";
import i18n from "i18next";

import { initI18n, normalizeLanguage, type AppLanguage } from "./init";

export function I18nProvider({
  language,
  children,
}: {
  language: AppLanguage | string;
  children: React.ReactNode;
}) {
  // Synchronous — ensures i18n is ready on the very first render (server and
  // client alike), so useTranslation() never falls back to raw keys.
  initI18n();

  useEffect(() => {
    let cancelled = false;
    const nextLang = normalizeLanguage(language);

    if (!cancelled && i18n.language !== nextLang) {
      i18n.changeLanguage(nextLang);
    }
    if (typeof document !== "undefined") {
      document.documentElement.lang = nextLang;
    }

    return () => { cancelled = true; };
  }, [language]);

  return children;
}
