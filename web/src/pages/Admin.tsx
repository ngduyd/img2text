import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { BarChart3, LayoutDashboard, ScrollText, Terminal, Users } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import AdminApi from "./admin/AdminApi";
import AdminLogs from "./admin/AdminLogs";
import AdminOverview from "./admin/AdminOverview";
import type { AdminTabId } from "./admin/AdminOverview";
import AdminStats from "./admin/AdminStats";
import AdminUsers from "./admin/AdminUsers";

// Plan V3: desktop ≥md = vertical sub-rail (icon + label); mobile = horizontal scroll pills. Testids tab-* kept (R51).
const TABS = [
  { id: "overview", label: "Tổng quan", icon: LayoutDashboard },
  { id: "users", label: "Người dùng", icon: Users },
  { id: "api", label: "API", icon: Terminal },
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "stats", label: "Thống kê", icon: BarChart3 },
] as const;

/** Admin-only page; tabs are in-page state (not routes). Non-admins go home. No jobs board. */
export default function Admin() {
  const navigate = useNavigate();
  const { data: me, isError } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const [tab, setTab] = useState<AdminTabId>("overview");

  // Unauthenticated /api/auth/me → 401; send to login, not a blank page.
  useEffect(() => {
    if (isError) navigate("/login");
  }, [isError, navigate]);

  useEffect(() => {
    // Non-admin authed → trang chủ "/" (Landing), consistent with root-as-home.
    if (me && me.role !== "admin") navigate("/");
  }, [me, navigate]);

  if (isError || (me && me.role !== "admin")) return null;

  return (
    <main id="main" className="mx-auto max-w-5xl p-4">
      <h1 className="mb-4 text-xl font-bold">Quản trị</h1>
      <div className="flex flex-col gap-4 md:flex-row md:gap-6">
        <nav
          data-testid="admin-rail"
          aria-label="Quản trị"
          className="flex shrink-0 gap-1 overflow-x-auto border-b border-border pb-2 md:sticky md:top-16 md:w-52 md:flex-col md:self-start md:overflow-visible md:border-b-0 md:border-r md:border-border md:pb-0"
        >
          {TABS.map((t) => {
            const active = tab === t.id;
            const Icon = t.icon;
            return (
              <button
                key={t.id}
                type="button"
                data-testid={`tab-${t.id}`}
                aria-current={active ? "page" : undefined}
                onClick={() => setTab(t.id)}
                className={[
                  "relative flex h-11 shrink-0 cursor-pointer items-center gap-2 rounded-md px-3 text-sm transition-colors duration-150 ease-out",
                  active
                    ? "bg-surface-2 font-semibold text-text after:absolute after:inset-y-1.5 after:left-0 after:w-1 after:rounded-full after:bg-accent"
                    : "text-muted hover:bg-surface-2 hover:text-text",
                ].join(" ")}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {t.label}
              </button>
            );
          })}
        </nav>
        <div className="min-w-0 flex-1">
          {!me ? (
            <div data-testid="admin-loading" className="p-8 text-center text-muted">
              Đang tải…
            </div>
          ) : (
            <>
              {tab === "overview" && <AdminOverview onNavigate={setTab} />}
              {tab === "users" && <AdminUsers />}
              {tab === "api" && <AdminApi />}
              {tab === "logs" && <AdminLogs />}
              {tab === "stats" && <AdminStats />}
            </>
          )}
        </div>
      </div>
    </main>
  );
}
