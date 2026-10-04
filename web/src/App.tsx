import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import Forgot from "./pages/Forgot";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Reset from "./pages/Reset";

/** Placeholder page — replaced by real pages in later tasks. */
function Placeholder({ name }: { name: string }) {
  return <main data-testid="page-placeholder">{name}</main>;
}

export default function App() {
  // BrowserRouter lives here (not main.tsx): App.test.tsx renders <App />
  // standalone, so the shell must be router-self-contained.
  return (
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
          <Route path="/" element={<Placeholder name="jobs" />} />
          <Route path="/jobs/:id" element={<Placeholder name="job detail" />} />
          <Route path="/admin" element={<Placeholder name="admin" />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
