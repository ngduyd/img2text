import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Link, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api/client";
import Forgot from "./pages/Forgot";
import Admin from "./pages/Admin";
import JobDetail from "./pages/JobDetail";
import Jobs from "./pages/Jobs";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Reset from "./pages/Reset";

// BrowserRouter + QueryClientProvider live here (not main.tsx): App.test.tsx
// renders <App /> standalone, so the shell must be provider-self-contained.
// Module scope so re-renders keep the cache.
const queryClient = new QueryClient();

/** Top nav. Logout button appears only when ["me"] resolves (spec §2 MVP). */
function AppNav() {
  const navigate = useNavigate();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });

  async function onLogout() {
    try {
      await api.logout();
    } catch {
      // best-effort: clear local session even if server call fails
    }
    queryClient.clear();
    navigate("/login");
  }

  return (
    <nav className="flex items-center gap-4 border-b border-gray-200 bg-white px-4 py-3">
      <Link to="/" data-testid="nav-brand" className="text-lg font-bold">
        img2text
      </Link>
      <Link to="/" data-testid="nav-link-jobs">
        Công việc
      </Link>
      <Link to="/admin" data-testid="nav-link-admin">
        Admin
      </Link>
      <Link to="/login" data-testid="nav-link-login">
        Đăng nhập
      </Link>
      {me && (
        <button
          type="button"
          data-testid="btn-logout"
          onClick={onLogout}
          className="ml-auto rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50"
        >
          Đăng xuất
        </button>
      )}
    </nav>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
      <div className="min-h-screen bg-gray-50 text-gray-900">
        <AppNav />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot" element={<Forgot />} />
          <Route path="/reset" element={<Reset />} />
          <Route path="/" element={<Jobs />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/admin" element={<Admin />} />
        </Routes>
      </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
