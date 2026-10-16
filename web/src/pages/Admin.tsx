import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { BarChart3, HardDrive, LayoutDashboard, MessageSquare, ScrollText, Settings, Terminal, Users } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useT } from "../i18n";
import AdminApi from "./admin/AdminApi";
import AdminFeedbacks from "./admin/AdminFeedbacks";
import AdminKaggleQuota from "./admin/AdminKaggleQuota";
import AdminLogs from "./admin/AdminLogs";
import AdminOverview from "./admin/AdminOverview";
import type { AdminTabId } from "./admin/AdminOverview";
import AdminSettings from "./admin/AdminSettings";
import AdminStats from "./admin/AdminStats";
import AdminStorage from "./admin/AdminStorage";
import AdminWorkers from "./admin/AdminWorkers";
import AdminUsers from "./admin/AdminUsers";
import PageShell from "../components/PageShell";
import Skeleton from "../components/ui/Skeleton";

// Plan V3: desktop ≥md = vertical sub-rail (icon + label); mobile = horizontal scroll pills. Testids tab-* kept (R51).
const TABS = [
  { id: "overview", labelKey: "admin.tab.overview", icon: LayoutDashboard },
  { id: "users", labelKey: "admin.tab.users", icon: Users },
  { id: "api", labelKey: "admin.tab.api", icon: Terminal },
  { id: "logs", labelKey: "admin.tab.logs", icon: ScrollText },
  { id: "stats", labelKey: "admin.tab.stats", icon: BarChart3 },
  { id: "storage", labelKey: "admin.tab.storage", icon: HardDrive },
  { id: "settings", labelKey: "admin.tab.settings", icon: Settings },
  // Lane B2 (wave-5 S6): feedback list.
  { id: "feedbacks", labelKey: "admin.tab.feedbacks", icon: MessageSquare },
] as const;

/** Admin-only page; tabs are in-page state (not routes). Non-admins go home. No jobs board. */
export default function Admin() {
  const { t } = useT();
  const navigate = useNavigate();
  const { data: me, isError } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const [tab, setTab] = useState<AdminTabId>("overview");

  // Unauthenticated /api/auth/me → 401; send to login, not a blank page.
  useEffect(() => {
    if (isError) navigate("/signin");
  }, [isError, navigate]);

  useEffect(() => {
    // Non-admin authed → trang chủ "/" (Landing), consistent with root-as-home.
    if (me && me.role !== "admin") navigate("/");
  }, [me, navigate]);

  if (isError || (me && me.role !== "admin")) return null;

  return (
    <PageShell width="wide">
      <h1 className="mb-4 text-xl font-bold">{t("admin.title")}</h1>
      <div className="flex flex-col gap-4 md:flex-row md:gap-6">
        <nav
          data-testid="admin-rail"
          aria-label={t("admin.title")}
          className="flex shrink-0 gap-1 overflow-x-auto border-b border-border pb-2 md:sticky md:top-16 md:w-52 md:flex-col md:self-start md:overflow-visible md:border-b-0 md:border-r md:border-border md:pb-0"
        >
          {TABS.map((tabDef) => {
            const active = tab === tabDef.id;
            const Icon = tabDef.icon;
            return (
              <button
                key={tabDef.id}
                type="button"
                data-testid={`tab-${tabDef.id}`}
                aria-current={active ? "page" : undefined}
                onClick={() => setTab(tabDef.id)}
                className={[
                  "relative flex h-11 shrink-0 cursor-pointer items-center gap-2 rounded-md px-3 text-sm transition-colors duration-150 ease-out",
                  active
                    ? "bg-surface-2 font-semibold text-text after:absolute after:inset-y-1.5 after:left-0 after:w-0.5 after:rounded-full after:bg-accent"
                    : "text-muted hover:bg-surface-2 hover:text-text",
                ].join(" ")}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {t(tabDef.labelKey)}
              </button>
            );
          })}
        </nav>
        <div className="min-w-0 flex-1">
          {!me ? (
            <Skeleton testid="admin-loading" className="h-10 w-full" />
          ) : (
            <>
              {tab === "overview" && <AdminOverview onNavigate={setTab} />}
              {tab === "users" && <AdminUsers />}
              {tab === "api" && <AdminApi />}
              {tab === "logs" && <AdminLogs />}
              {tab === "stats" && <AdminStats />}
              {tab === "storage" && <AdminStorage />}
              {tab === "settings" && (
                <div className="flex flex-col gap-4">
                  {/* Spec #7 Workers + Lane K quota GPU — luôn-đồ-nhìn → System tab. */}
                  <AdminWorkers />
                  <AdminKaggleQuota />
                  <AdminSettings />
                </div>
              )}
              {tab === "feedbacks" && <AdminFeedbacks />}
            </>
          )}
        </div>
      </div>
    </PageShell>
  );
}
