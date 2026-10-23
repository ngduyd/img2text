import { Link } from "react-router-dom";
import { useT } from "../i18n";

/** Link trong footer: min-h 24px để đủ target size WCAG 2.2 (2.5.8). */
const LINK = "inline-flex min-h-6 items-center hover:text-text";

/** Global footer (every page, under Routes): copyright + email + site + feedback. */
export default function SiteFooter() {
  const { t } = useT();
  return (
    <footer data-testid="site-footer" aria-label={t("footer.aria")} className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 text-sm text-muted sm:flex-row sm:items-center sm:justify-between">
        <span>{t("footer.copyright")}</span>
        <nav className="flex flex-wrap items-center gap-x-4" aria-label={t("footer.linksAria")}>
          <a href="mailto:nguyenduy2004.d@gmail.com" className={LINK}>
            nguyenduy2004.d@gmail.com
          </a>
          <a href="https://ngduyd.id.vn" target="_blank" rel="noopener noreferrer" className={LINK}>
            ngduyd.id.vn
          </a>
          <Link to="/feedback" className={LINK}>
            {t("footer.feedback")}
          </Link>
        </nav>
      </div>
    </footer>
  );
}
