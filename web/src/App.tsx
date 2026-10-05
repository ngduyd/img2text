import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { BrowserRouter, Link, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api/client";
import type { User } from "./api/types";
import ThemeToggle from "./components/ThemeToggle";
import Badge from "./components/ui/Badge";
import Button, { buttonClasses } from "./components/ui/Button";
import Forgot from "./pages/Forgot";
import Admin from "./pages/Admin";
import JobDetail from "./pages/JobDetail";
import Jobs from "./pages/Jobs";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Reset from "./pages/Reset";

// BrowserRouter + QueryClientProvider live here (not main.tsx): App.test.tsx
// renders <App /> standalone, so the shell must be provider-self-contained.
// Module scope so re-renders keep the cache. Exported: App.test.tsx clears it
// per test (fresh mount must not inherit another test's ["me"] resolution).
export const queryClient = new QueryClient();

/** OCR status in right auth zone (binding nav contract, Task 0). */
function OcrBadge({ enabled }: { enabled: boolean }) {
  return enabled ? (
    <Badge tone="success" testid="badge-ocr">
      OCR đã cấp
    </Badge>
  ) : (
    <Badge tone="warning" testid="badge-ocr">
      Chờ admin cấp quyền
    </Badge>
  );
}

/** RIGHT auth zone: logged-out btn-login+btn-register; logged-in badge+avatar+profile+logout. */
function AuthZone({ me, onLogout }: { me: User | undefined; onLogout: () => void }) {
  return (
    <div data-testid="auth-zone" className="flex items-center gap-2">
      <ThemeToggle />
      {me ? (
        <>
          <OcrBadge enabled={me.ocr_enabled} />
          <span
            data-testid="nav-avatar"
            title={me.role}
            aria-label={me.role}
            className="flex h-7 w-7 items-center justify-center rounded-full border border-border bg-surface text-xs font-semibold"
          >
            {(me.email ?? "").slice(0, 2).toUpperCase() || "?"}
          </span>
          <Link to="/profile" data-testid="btn-profile" className={buttonClasses("ghost", "sm")}>
            Hồ sơ
          </Link>
          <Button variant="danger" size="sm" testid="btn-logout" onClick={onLogout}>
            Đăng xuất
          </Button>
        </>
      ) : (
        <>
          <Link to="/login" data-testid="btn-login" className={buttonClasses("primary", "sm")}>
            Đăng nhập
          </Link>
          <Link to="/register" data-testid="btn-register" className={buttonClasses("ghost", "sm")}>
            Đăng ký
          </Link>
        </>
      )}
    </div>
  );
}

/** Left nav: brand + Công việc (non-admin) + Quản trị (admin only, Review Focus). */
function AppNav() {
  const navigate = useNavigate();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const [menuOpen, setMenuOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);

  async function onLogout() {
    try {
      await api.logout();
    } catch {
      // best-effort: clear local session even if server call fails
    }
    queryClient.clear();
    navigate("/login");
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
  const showJobs = !isAdmin;

  return (
    <nav
      ref={navRef}
      aria-label="Điều hướng chính"
      className="sticky top-0 z-20 border-b border-border bg-bg/80 backdrop-blur"
    >
      <div className="mx-auto flex max-w-5xl items-center gap-4 px-4 py-3">
        <Link to="/" data-testid="nav-brand" className="text-lg font-bold">
          img2text
        </Link>
        {showJobs && (
          <Link to="/" data-testid="nav-link-jobs" onClick={() => setMenuOpen(false)}>
            Công việc
          </Link>
        )}
        {isAdmin && (
          <Link to="/admin" data-testid="nav-link-admin" onClick={() => setMenuOpen(false)}>
            Quản trị
          </Link>
        )}
        <div className="ml-auto hidden items-center gap-2 md:flex">
          <AuthZone me={me} onLogout={onLogout} />
        </div>
        <button
          type="button"
          data-testid="nav-menu-toggle"
          className="ml-auto cursor-pointer rounded-lg border border-border px-2 py-1 md:hidden"
          aria-expanded={menuOpen}
          aria-controls="mobile-menu"
          aria-label="Menu"
          onClick={() => setMenuOpen((o) => !o)}
        >
          <span aria-hidden="true">☰</span>
        </button>
      </div>
      {menuOpen && (
        <div
          id="mobile-menu"
          data-testid="mobile-menu"
          className="border-t border-border bg-bg px-4 py-3 md:hidden"
        >
          <div className="flex flex-col items-start gap-2">
            {showJobs && (
              <Link to="/" data-testid="nav-link-jobs" onClick={() => setMenuOpen(false)}>
                Công việc
              </Link>
            )}
            {isAdmin && (
              <Link to="/admin" data-testid="nav-link-admin" onClick={() => setMenuOpen(false)}>
                Quản trị
              </Link>
            )}
            <AuthZone
              me={me}
              onLogout={() => {
                setMenuOpen(false);
                onLogout();
              }}
            />
          </div>
        </div>
      )}
    </nav>
  );
}

/** Task 3 placeholder — /profile route lands with the Profile page. */
function ProfilePlaceholder() {
  return (
    <main id="main" className="mx-auto max-w-3xl p-4">
      <h1 className="mb-4 text-xl font-bold">Hồ sơ</h1>
      <p className="text-muted">Trang hồ sơ đang được xây dựng.</p>
    </main>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-screen">
          <a href="#main" className="skip-link">
            Bỏ qua điều hướng
          </a>
          <AppNav />
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/forgot" element={<Forgot />} />
            <Route path="/reset" element={<Reset />} />
            <Route path="/profile" element={<ProfilePlaceholder />} />
            <Route path="/" element={<Jobs />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
            <Route path="/admin" element={<Admin />} />
          </Routes>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
