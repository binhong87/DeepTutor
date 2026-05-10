"use client";

import { useEffect, useRef } from "react";
import i18n from "i18next";

import { initI18n, normalizeLanguage, type AppLanguage } from "./init";

let _initPromise: Promise<unknown> | null = null;

function ensureI18n() {
  if (!_initPromise) {
    _initPromise = initI18n();
  }
  return _initPromise;
}

export function I18nProvider({
  language,
  children,
}: {
  language: AppLanguage | string;
  children: React.ReactNode;
}) {
  const initialized = useRef(false);

  if (!initialized.current) {
    ensureI18n();
    initialized.current = true;
  }

  useEffect(() => {
    let cancelled = false;
    const nextLang = normalizeLanguage(language);

    ensureI18n().then(() => {
      if (cancelled) return;
      if (i18n.language !== nextLang) {
        i18n.changeLanguage(nextLang);
      }
      if (typeof document !== "undefined") {
        document.documentElement.lang = nextLang;
      }
    });

    return () => { cancelled = true; };
  }, [language]);

  return children;
}
