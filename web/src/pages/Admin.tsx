import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import Button from "../components/ui/Button";
import AdminApi from "./admin/AdminApi";
import AdminLogs from "./admin/AdminLogs";
import AdminOverview from "./admin/AdminOverview";
import type { AdminTabId } from "./admin/AdminOverview";
import AdminStats from "./admin/AdminStats";
import AdminUsers from "./admin/AdminUsers";

const TABS = [
  { id: "overview", label: "Tổng quan" },
  { id: "users", label: "Người dùng" },
  { id: "api", label: "API" },
  { id: "logs", label: "Logs" },
  { id: "stats", label: "Thống kê" },
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
    if (me && me.role !== "admin") navigate("/");
  }, [me, navigate]);

  if (isError || (me && me.role !== "admin")) return null;

  return (
    <main id="main" className="mx-auto max-w-5xl p-4">
      <h1 className="mb-4 text-xl font-bold">Quản trị</h1>
      <div className="mb-4 flex gap-2 border-b border-border">
        {TABS.map((t) => (
          <Button
            key={t.id}
            testid={`tab-${t.id}`}
            variant="ghost"
            className={
              tab === t.id
                ? "border-b-2 border-accent font-semibold text-accent"
                : "text-muted"
            }
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </Button>
        ))}
      </div>
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
    </main>
  );
}
