import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import Forgot from "./pages/Forgot";
import Admin from "./pages/Admin";
import JobDetail from "./pages/JobDetail";
import Jobs from "./pages/Jobs";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Reset from "./pages/Reset";

export default function App() {
  // BrowserRouter + QueryClientProvider live here (not main.tsx): App.test.tsx
  // renders <App /> standalone, so the shell must be provider-self-contained.
  return (
    <QueryClientProvider client={new QueryClient()}>
      <BrowserRouter>
      <div className="min-h-screen bg-gray-50 text-gray-900">
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
        </nav>
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
