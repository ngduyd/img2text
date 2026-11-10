import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ScanText } from "lucide-react";
import { useT } from "../i18n";

interface AuthLayoutProps {
  title: string;
  subtitle: string;
  footer: ReactNode;
  children: ReactNode;
  /** Panel giới thiệu bên trái — chỉ hiện ≥lg (form vẫn là trung tâm ở mobile). */
  aside?: ReactNode;
}

export default function AuthLayout({
  title,
  subtitle,
  footer,
  children,
  aside,
}: AuthLayoutProps) {
  const { t } = useT();
  return (
    <main id="main" className="flex min-h-dvh flex-col justify-start px-4 pt-10 pb-10 lg:pt-24">
      <div className="mx-auto flex w-full max-w-sm flex-col lg:max-w-4xl lg:flex-row lg:items-start lg:gap-16">
        {aside && (
          <div className="hidden flex-1 lg:block lg:pt-2" data-testid="auth-aside">
            {aside}
          </div>
        )}
        <div className="w-full lg:max-w-sm" data-testid="auth-card">
        <Link
          to="/"
          className="mb-6 flex items-center justify-center gap-2"
          aria-label={t("common.homeAria")}
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-accent">
            <ScanText className="h-5 w-5 text-accent-contrast" aria-hidden="true" />
          </span>
          <span className="text-lg font-bold tracking-tight text-text">img2text</span>
        </Link>
        <div className="rounded-card border border-border bg-surface p-6 shadow-card">
          <h1 className="text-xl font-bold text-text">{title}</h1>
          <p className="mt-1 text-sm text-muted">{subtitle}</p>
          <div className="mt-6">{children}</div>
        </div>
        <p className="mt-4 text-center text-sm text-muted">{footer}</p>
        </div>
      </div>
    </main>
  );
}
