import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Briefcase, HardDrive, IdCard, LogOut, Menu, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { Toaster, toast } from "sonner";
import { api } from "./api/client";
import type { User } from "./api/types";
import ThemeToggle from "./components/ThemeToggle";
import OcrBadge from "./components/OcrBadge";
import LangSwitch from "./components/LangSwitch";
import SiteFooter from "./components/SiteFooter";
import VerifyGate from "./components/VerifyGate";
import Button, { buttonClasses } from "./components/ui/Button";
import Forgot from "./pages/Forgot";
import Feedback from "./pages/Feedback";
import Admin from "./pages/Admin";
import JobDetail from "./pages/JobDetail";
import ExtractionPage from "./pages/ExtractionPage";
import Jobs from "./pages/Jobs";
import Storage from "./pages/Storage";
import Landing from "./pages/Landing";
import Signin from "./pages/Signin";
import Profile from "./pages/Profile";
import Signup from "./pages/Signup";
import Reset from "./pages/Reset";
import { mapApiError } from "./lib/errors";
import { I18nProvider, useT } from "./i18n";

// BrowserRouter + QueryClientProvider live here (not main.tsx): App.test.tsx
// renders <App /> standalone, so the shell must be provider-self-contained.
// Module scope so re-renders keep the cache. Exported: App.test.tsx clears it
// per test (fresh mount must not inherit another test's ["me"] resolution).
export const queryClient = new QueryClient();

/** RIGHT auth zone — SPEC-ui-redesign D2: nav chỉ còn 3 link + quota chip + avatar.
 *  Logged-out: theme + lang + Sign in/Up (không có avatar để chứa menu).
 *  Logged-in : quota chip + cảnh báo OCR (nếu tắt) + avatar → menu (quota, lang,
 *              theme, OCR, Profile, Logout). */
export function AuthZone({ me, onLogout }: { me: User | undefined; onLogout: () => void }) {
  const { t } = useT();
  if (me) return <NavUser me={me} onLogout={onLogout} />;
  return (
    <div data-testid="auth-zone" className="flex items-center gap-2">
      <ThemeToggle />
      <LangSwitch testid="lang-switch-nav" />
      <Link to="/signin" data-testid="btn-login" className={buttonClasses("primary", "sm")}>
        {t("nav.signIn")}
      </Link>
      <Link to="/signup" data-testid="btn-register" className={buttonClasses("ghost", "sm")}>
        {t("nav.signUp")}
      </Link>
    </div>
  );
}

/** Logged-in cluster: quota chip + (OCR warning) + avatar dropdown. */
function NavUser({ me, onLogout }: { me: User; onLogout: () => void }) {
  const { t } = useT();
  const [menuOpen, setMenuOpen] = useState(false);
  const userRef = useRef<HTMLDivElement>(null);
  const name = me.email || me.role || "";
  const { data: quota } = useQuery({ queryKey: ["quota"], queryFn: api.getMyQuota, retry: false });

  // Dropdown: close on outside click (same pattern as AppNav navRef).
  useEffect(() => {
    if (!menuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (userRef.current && !userRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  const quotaText = quota
    ? t("quota.remaining", {
        dUsed: quota.daily_remaining,
        dLimit: quota.daily_limit,
        wUsed: quota.weekly_remaining,
        wLimit: quota.weekly_limit,
      })
    : "";

  return (
    <div data-testid="auth-zone" className="flex items-center gap-2">
      {/* Chip gọn: chỉ số ngày; text đầy đủ nằm trong menu (title = tooltip). */}
      {quota && (
        <span
          data-testid="quota-chip"
          title={quotaText}
          className="hidden rounded-full border border-border px-2 py-0.5 text-xs tabular-nums text-muted sm:inline"
        >
          {quota.daily_remaining}/{quota.daily_limit}
        </span>
      )}
      {/* Cảnh báo khi OCR chưa được cấp — trạng thái actionable duy nhất cần thấy ngay. */}
      {!me.ocr_enabled && <OcrBadge enabled={false} />}
      <div ref={userRef} className="relative flex items-center">
        <button
          type="button"
          data-testid="nav-avatar"
          title={name}
          aria-label={name}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((o) => !o)}
          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-full border border-border bg-surface text-xs font-semibold"
        >
          {(me.email ?? "").slice(0, 2).toUpperCase() || "?"}
        </button>
        {menuOpen && (
          <div
            data-testid="nav-user-menu"
            role="menu"
            className="absolute right-0 top-full z-30 mt-2 w-64 rounded-card border border-border bg-surface p-2 text-left shadow-card"
          >
            <div className="px-2 py-1">
              <div className="truncate font-medium text-text">{me.email}</div>
              <div className="text-muted">{me.role}</div>
            </div>
            {quota && (
              <p data-testid="quota-remaining" className="px-2 py-1 text-xs text-muted">
                {quotaText}
              </p>
            )}
            <div className="my-1 border-t border-border" />
            <div className="flex items-center justify-between gap-2 px-2 py-1 text-sm">
              <span className="text-muted">{t("nav.language")}</span>
              <LangSwitch testid="lang-switch-nav" />
            </div>
            <div className="flex items-center justify-between gap-2 px-2 py-1 text-sm">
              <span className="text-muted">{t("nav.theme")}</span>
              <ThemeToggle />
            </div>
            <div className="flex items-center justify-between gap-2 px-2 py-1 text-sm">
              <span className="text-muted">{t("nav.ocr")}</span>
              <OcrBadge enabled={me.ocr_enabled} testid="badge-ocr-menu" />
            </div>
            <div className="my-1 border-t border-border" />
            <Link
              to="/profile"
              data-testid="btn-profile"
              role="menuitem"
              onClick={() => setMenuOpen(false)}
              className={`${buttonClasses("ghost", "sm")} w-full justify-start`}
            >
              <IdCard className="h-4 w-4" aria-hidden="true" />
              {t("nav.profile")}
            </Link>
            <Button
              variant="danger"
              size="sm"
              testid="btn-logout"
              onClick={onLogout}
              className="w-full justify-start"
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
              {t("nav.logout")}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

/** Active nav link: accent left-bar + surface-2 tint (DESIGN.md §4/§7). */
function navLinkClass(active: boolean): string {
  return [
    "relative flex items-center gap-2 rounded-sm px-3 py-2 text-sm transition duration-150 ease-out",
    active
      ? "bg-surface-2 font-semibold text-text after:absolute after:inset-y-1.5 after:left-0 after:w-0.5 after:rounded-full after:bg-accent"
      : "text-muted hover:bg-surface-2 hover:text-text",
  ].join(" ");
}

/** Nav link: lucide icon + label; active adds aria-current="page". */
function NavAnchor({
  to,
  testid,
  icon: Icon,
  active,
  onClick,
  children,
}: {
  to: string;
  testid: string;
  icon: typeof Briefcase;
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      data-testid={testid}
      aria-current={active ? "page" : undefined}
      className={navLinkClass(active)}
      onClick={onClick}
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      {children}
    </Link>
  );
}

/** Left nav: brand + Công việc (everyone) + Quản trị (admin only, Review Focus). */
function AppNav() {
  const navigate = useNavigate();
  const { t } = useT();
  const { pathname } = useLocation();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const [menuOpen, setMenuOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);

  async function onLogout() {
    try {
      await api.logout();
      toast.success(t("nav.signedOut"));
    } catch (err) {
      // best-effort: clear local session even if server call fails
      toast.error(mapApiError(err));
    }
    queryClient.clear();
    navigate("/signin");
  }

  // Hamburger: close on outside click.
  useEffect(() => {
    if (!menuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (navRef.current && !navRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  const isAdmin = me?.role === "admin";
  const jobsActive = pathname === "/jobs";
  const storageActive = pathname === "/storage";
  const adminActive = pathname.startsWith("/admin");

  return (
    <nav
      ref={navRef}
      aria-label={t("nav.ariaMain")}
      className="sticky top-0 z-20 border-b border-border bg-bg/80 backdrop-blur"
    >
      {/* Single-line bar: ~56px mobile / 64px desktop (DESIGN.md §7). */}
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-1 px-4 md:h-16">
        <Link
          to="/"
          data-testid="nav-brand"
          className="mr-2 shrink-0 text-lg font-bold tracking-tight"
        >
          img2text
        </Link>
        <div className="hidden items-center gap-1 md:flex">
          <NavAnchor
            to="/jobs"
            testid="nav-link-jobs"
            icon={Briefcase}
            active={jobsActive}
            onClick={() => setMenuOpen(false)}
          >
            {t("nav.jobs")}
          </NavAnchor>
          <NavAnchor
            to="/storage"
            testid="nav-link-storage"
            icon={HardDrive}
            active={storageActive}
            onClick={() => setMenuOpen(false)}
          >
            {t("nav.storage")}
          </NavAnchor>
          {isAdmin && (
            <NavAnchor
              to="/admin"
              testid="nav-link-admin"
              icon={ShieldCheck}
              active={adminActive}
              onClick={() => setMenuOpen(false)}
            >
              {t("nav.admin")}
            </NavAnchor>
          )}
        </div>
        <div className="ml-auto hidden items-center gap-2 md:flex">
          <AuthZone me={me} onLogout={onLogout} />
        </div>
        <button
          type="button"
          data-testid="nav-menu-toggle"
          className="ml-auto inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md border border-border text-text transition duration-150 ease-out hover:bg-surface-2 md:hidden"
          aria-expanded={menuOpen}
          aria-controls="mobile-menu"
          aria-label={t("nav.menu")}
          title={t("nav.menu")}
          onClick={() => setMenuOpen((o) => !o)}
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>
      {menuOpen && (
        <div
          id="mobile-menu"
          data-testid="mobile-menu"
          className="border-t border-border bg-bg px-4 py-3 md:hidden"
        >
          <div className="flex flex-col items-stretch gap-1">
            <NavAnchor
              to="/jobs"
              testid="nav-link-jobs"
              icon={Briefcase}
              active={jobsActive}
              onClick={() => setMenuOpen(false)}
            >
              {t("nav.jobs")}
            </NavAnchor>
            <NavAnchor
              to="/storage"
              testid="nav-link-storage"
              icon={HardDrive}
              active={storageActive}
              onClick={() => setMenuOpen(false)}
            >
              {t("nav.storage")}
            </NavAnchor>
            {isAdmin && (
              <NavAnchor
                to="/admin"
                testid="nav-link-admin"
                icon={ShieldCheck}
                active={adminActive}
                onClick={() => setMenuOpen(false)}
              >
                {t("nav.admin")}
              </NavAnchor>
            )}
            <div className="mt-2 border-t border-border pt-3">
              <AuthZone
                me={me}
                onLogout={() => {
                  setMenuOpen(false);
                  onLogout();
                }}
              />
            </div>
          </div>
        </div>
      )}
    </nav>
  );
}

/**
 * Root route: Landing ALWAYS — the trang chủ (home page) for every auth state
 * (user report: "đăng nhập rồi không nhảy về trang chủ được nữa"). No
 * logged-in redirect; AppNav fetches ["me"] for the auth zone + admin link.
 */

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <BrowserRouter>
          <div className="min-h-dvh">
            <a href="#main" className="skip-link">
              <SkipLabel />
            </a>
          <AppNav />
          {/* Theme = html .dark class (ThemeToggle + localStorage; no shared React
              context) — read once at mount; toggle flips CSS only. */}
          <Toaster
            theme={document.documentElement.classList.contains("dark") ? "dark" : "light"}
            position="top-right"
            richColors
          />
          <Routes>
            <Route path="/signin" element={<Signin />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/forgot" element={<Forgot />} />
            <Route path="/reset" element={<Reset />} />
            <Route path="/profile" element={<Profile />} />
            {/* Lane B2 (wave-5 S6): trang góp ý — link ở footer do Lane B1 thêm. */}
            <Route path="/feedback" element={<Feedback />} />
            <Route path="/" element={<Landing />} />
            <Route path="/landing" element={<Navigate to="/" replace />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
            {/* SPEC-ui-redesign D3: 2 trang con tách khỏi JobDetail. */}
            <Route path="/jobs/:id/text" element={<JobDetail section="text" />} />
            <Route path="/jobs/:id/layout" element={<JobDetail section="layout" />} />
            {/* Phase 2 (Sub-system B): trang trích xuất — highlight + click-fix + save-sync. */}
            <Route path="/jobs/:id/extraction" element={<ExtractionPage />} />
            {/* R51 exception (user: "không tách /edit nữa"): standalone /edit page
                gộp vào /jobs/:id (JD2 mount) — bookmark cũ redirect trang chủ. */}
            <Route path="/edit" element={<Navigate to="/" replace />} />
            <Route path="/word" element={<Navigate to="/" replace />} />
            <Route path="/admin" element={<Admin />} />
            {/* Lane B1: trang "In the feature" — bản kế tiếp (Organizations). */}
            {/* Roadmap gộp vào Landing: bookmark cũ → /#roadmap. */}
            <Route path="/features" element={<Navigate to="/#roadmap" replace />} />
            <Route path="/storage" element={<Storage />} />
          </Routes>
          {/* Global footer: mọi trang, dưới Routes (App không dùng Outlet). */}
          <SiteFooter />
          {/* Lane C2 (S5): gating verify — overlay toàn màn, nav+vùng content vẫn render. */}
          <VerifyGate />
        </div>
      </BrowserRouter>
      </I18nProvider>
    </QueryClientProvider>
  );
}

/** Skip-link label needs useT inside I18nProvider. */
function SkipLabel() {
  const { t } = useT();
  return <>{t("nav.skip")}</>;
}
