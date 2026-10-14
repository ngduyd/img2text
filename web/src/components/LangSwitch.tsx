import { useT, type Lang } from "../i18n";

const OPTIONS: { code: Lang; label: string; testid: string }[] = [
  { code: "vi", label: "VI", testid: "lang-vi" },
  { code: "en", label: "EN", testid: "lang-en" },
];

/** Spec S2: VI/EN switch (Nav + Landing header + Settings) → localStorage("lang"). */
export default function LangSwitch({ testid = "lang-switch" }: { testid?: string }) {
  const { t, lang, setLang } = useT();
  return (
    <div
      role="group"
      aria-label={t("common.language")}
      data-testid={testid}
      className="flex items-center rounded-md border border-border text-sm"
    >
      {OPTIONS.map((o) => (
        <button
          key={o.code}
          type="button"
          data-testid={`${testid}-${o.code}`}
          aria-pressed={lang === o.code}
          onClick={() => setLang(o.code)}
          className={`cursor-pointer px-2 py-1 ${
            lang === o.code ? "bg-surface-2 font-semibold text-text" : "text-muted hover:text-text"
          }`}
        >
          {t(`lang.${o.code}`)}
        </button>
      ))}
    </div>
  );
}
