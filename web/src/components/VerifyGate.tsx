import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api, onEmailUnverified } from "../api/client";
import VerifyModal from "./VerifyModal";

/** Lane C2 (S5): route guard — login/register/features ngoài gating; mọi trang
 *  app còn lại khi unverified → modal overlay (nội dung KHÔNG bị ẩn). */
const EXEMPT_ROUTES = ["/signin", "/signup", "/features"];

/** Global gating: (a) 403 email_unverified từ bất kỳ API call nào (listener trong
 *  request()) hoặc (b) ["me"] trả is_verified=false → hiện VerifyModal.
 *  Refetch ["me"] sau verify nên app tự unlock; verify xong → đóng modal. */
export default function VerifyGate() {
  const { pathname } = useLocation();
  const queryClient = useQueryClient();
  // Query ["me"] trùng key với AppNav → 1 cache entry, không fetch thừa.
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const [gated, setGated] = useState(false);

  useEffect(() => onEmailUnverified(() => setGated(true)), []);

  async function handleVerified() {
    setGated(false);
    await queryClient.invalidateQueries({ queryKey: ["me"] });
  }

  function handleLogout() {
    // Best-effort: điều hướng do <Link> lo; cache clear để về trạng thái đăng xuất.
    void api.logout().catch(() => {});
    queryClient.clear();
  }

  if (EXEMPT_ROUTES.includes(pathname)) return null;
  if (!gated && me?.is_verified !== false) return null;
  return (
    <VerifyModal email={me?.email} onVerified={handleVerified} onLogout={handleLogout} />
  );
}
