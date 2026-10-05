import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import AdminLogs from "../components/AdminLogs";
import AdminStats from "../components/AdminStats";
import AdminUsers from "../components/AdminUsers";
import Button from "../components/ui/Button";

const TABS = [
  { id: "users", label: "Người dùng" },
  { id: "stats", label: "Thống kê" },
  { id: "logs", label: "Logs" },
] as const;
type TabId = (typeof TABS)[number]["id"];

/** Admin-only page; tabs are in-page state (not routes). Non-admins go home. */
export default function Admin() {
  const navigate = useNavigate();
  const { data: me, isError } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const [tab, setTab] = useState<TabId>("users");

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
          {tab === "users" && <AdminUsers />}
          {tab === "stats" && <AdminStats />}
          {tab === "logs" && <AdminLogs />}
        </>
      )}
    </main>
  );
}
