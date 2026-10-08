import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ScanText } from "lucide-react";

interface AuthLayoutProps {
  title: string;
  subtitle: string;
  footer: ReactNode;
  children: ReactNode;
}

export default function AuthLayout({ title, subtitle, footer, children }: AuthLayoutProps) {
  return (
    <main id="main" className="flex min-h-dvh flex-col justify-center px-4 py-10">
      <div className="mx-auto w-full max-w-sm">
        <Link
          to="/"
          className="mb-6 flex items-center justify-center gap-2"
          aria-label="img2text home"
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
    </main>
  );
}
