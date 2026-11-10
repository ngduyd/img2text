import { FileText, Languages, ShieldCheck } from "lucide-react";
import { useT } from "../i18n";

/** Panel giới thiệu dùng chung cho MỌI trang auth (đăng nhập, đăng ký, mã xác
 *  nhận, quên/đặt lại mật khẩu). Dùng chung để bố cục không nhảy: nếu trang này
 *  có panel mà trang kia không, cột form lệch trái/phải khi chuyển bước. */
export default function AuthIntro() {
  const { t } = useT();
  const points = [
    { icon: FileText, text: t("auth.signup.aside1") },
    { icon: Languages, text: t("auth.signup.aside2") },
    { icon: ShieldCheck, text: t("auth.signup.aside3") },
  ];
  return (
    <div className="flex h-full flex-col justify-start">
      {/* Không border/bg: form card phải là card DUY NHẤT trên màn, nếu không
          hai khối cùng viền đọc như hai form cạnh nhau. */}
      <h2 className="text-lg font-semibold leading-snug text-text">
        {t("auth.signup.asideTitle")}
      </h2>
      <ul className="mt-5 flex flex-col gap-4">
        {points.map(({ icon: Icon, text }) => (
          <li key={text} className="flex gap-3 text-sm text-muted">
            <Icon className="mt-0.5 h-4 w-4 shrink-0 text-accent-text" aria-hidden="true" />
            <span className="leading-relaxed">{text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
