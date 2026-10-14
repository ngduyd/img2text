import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import en from "./en.json";
import viDict from "./vi.json";

export type Lang = "en" | "vi";

const DICTS: Record<Lang, Record<string, unknown>> = { en, vi: viDict };
export const LANG_KEY = "lang";

/** Spec S2: default "en"; stored lang wins (read before render). */
export function readLang(): Lang {
  return localStorage.getItem(LANG_KEY) === "vi" ? "vi" : "en";
}

function lookup(dict: Record<string, unknown>, key: string): string | undefined {
  let cur: unknown = dict;
  for (const part of key.split(".")) {
    if (typeof cur !== "object" || cur === null) return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return typeof cur === "string" ? cur : undefined;
}

/** Dot-namespaced key → localized string; fallback chain: lang → en → key. */
function translateIn(lang: Lang, key: string, params?: Record<string, string | number>): string {
  let s = lookup(DICTS[lang], key) ?? lookup(DICTS.en, key) ?? key;
  if (params)
    for (const [k, v] of Object.entries(params)) s = s.split(`{${k}}`).join(String(v));
  return s;
}

/** Module-level translate (lib/hooks/toasts — outside React render). */
export function translate(key: string, params?: Record<string, string | number>): string {
  return translateIn(readLang(), key, params);
}

interface I18nCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
}

// Default ctx getter keeps components usable WITHOUT provider (unit tests):
// render-time localStorage read, default "en".
const I18nContext = createContext<I18nCtx>({
  get lang() {
    return readLang();
  },
  setLang: (l: Lang) => {
    localStorage.setItem(LANG_KEY, l);
  },
});

/** Spec S2: React context provider — lang state + localStorage persistence. */
export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readLang);
  const setLang = useCallback((l: Lang) => {
    localStorage.setItem(LANG_KEY, l);
    setLangState(l);
  }, []);
  return <I18nContext.Provider value={{ lang, setLang }}>{children}</I18nContext.Provider>;
}

/** Spec S2 hook: `{ t, lang, setLang }`. */
export function useT(): {
  t: (key: string, params?: Record<string, string | number>) => string;
  lang: Lang;
  setLang: (l: Lang) => void;
} {
  const { lang, setLang } = useContext(I18nContext);
  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => translateIn(lang, key, params),
    [lang],
  );
  return { t, lang, setLang };
}
