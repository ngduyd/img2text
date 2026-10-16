import { Boxes, HardDrive, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import PageShell from "../components/PageShell";
import Badge from "../components/ui/Badge";
import { buttonClasses } from "../components/ui/Button";
import { useT } from "../i18n";

/**
 * "In the feature" — editorial-clean intro of the NEXT release (Organizations).
 * Announcement page, not a landing redesign: hero + 3 feature cards, no bitmaps.
 */

const CARDS: { testid: string; icon: LucideIcon; title: string; desc: string }[] = [
  { testid: "feature-card-workers", icon: Boxes, title: "features.workers.title", desc: "features.workers.desc" },
  { testid: "feature-card-storage", icon: HardDrive, title: "features.storage.title", desc: "features.storage.desc" },
  { testid: "feature-card-members", icon: Users, title: "features.members.title", desc: "features.members.desc" },
];

export default function Features() {
  const { t } = useT();
  return (
    <PageShell width="wide" testid="features-page">
      {/* Hero: left-aligned (editorial), one accent via badge. Fits first viewport. */}
      <section data-testid="features-hero" className="max-w-2xl">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold tracking-tight text-text md:text-4xl">{t("features.title")}</h1>
          <Badge tone="info" testid="features-badge">
            {t("features.subtitle")}
          </Badge>
        </div>
        <p className="mt-4 text-base leading-relaxed text-muted">{t("features.intro")}</p>
      </section>

      {/* 3 cards: mobile 1-col / desktop 3-col grid, radius-card, hairline border. */}
      <ul className="mt-10 grid grid-cols-1 gap-6 md:mt-12 md:grid-cols-2">
        {CARDS.map(({ testid, icon: Icon, title, desc }, i) => (
          <li
            key={testid}
            data-testid={testid}
            className={`rounded-card border border-border bg-surface p-6 ${i === 2 ? "md:col-span-2" : ""}`}
          >
            <div className="flex items-center gap-3">
              <Icon className="h-5 w-5 text-accent-text" aria-hidden="true" />
              <h2 className="text-base font-semibold text-text">{t(title)}</h2>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-muted">{t(desc)}</p>
          </li>
        ))}
      </ul>
      <div className="mt-10 text-center">
        <Link to="/jobs" className={buttonClasses("primary", "md")}>
          {t("landing.cta")}
        </Link>
      </div>
    </PageShell>
  );
}
