import DOMPurify from "dompurify";
import { useEffect, useRef, useState } from "react";
import { useT } from "../../i18n";

/** A4 thật (paged.js chia trang) — nền trắng vì đây là tờ giấy, không phải UI. */
const PAGE_CSS = `
@page { size: A4; margin: 20mm 18mm; }
/* zoom: thu A4 (794px @96dpi) vừa pane hẹp; zoom giữ đúng khung layout + scroll. */
.pagedjs_pages { display: flex; flex-direction: column; align-items: center; gap: 12px; zoom: .72; }
.pagedjs_page {
  /* !important: css tài liệu (theme tối) nạp trước có thể set background/color. */
  background: #fff !important; color: #111 !important;
  box-shadow: 0 1px 3px rgba(0,0,0,.4);
}
.pagedjs_page_content { overflow-wrap: break-word; }
.pagedjs_page table { border-collapse: collapse; }
.pagedjs_page td, .pagedjs_page th { border: 1px solid #999; padding: 4px 6px; }
`;

/**
 * D7: xem trước A4 chia trang thật (paged.js) song song editor, debounce 500ms.
 * ponytail: paged.js nặng + cần layout engine thật → lazy import, môi trường
 * không chạy được (jsdom) thì fallback HTML thường, không vỡ trang soạn.
 * Nâng cấp: đổi sang iframe riêng nếu cần cô lập CSS của app.
 */
export default function PagePreview({ html, css }: { html: string; css?: string }) {
  const { t } = useT();
  const hostRef = useRef<HTMLDivElement>(null);
  const [pages, setPages] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Ranh giới tin cậy: nội dung đến từ docx tải lên → sanitize TRƯỚC khi paged.js
    // (và trước cả nhánh fallback innerHTML) để không có script trong DOM.
    const safe = DOMPurify.sanitize(html);
    const timer = setTimeout(async () => {
      const host = hostRef.current;
      if (!host) return;
      try {
        const { Previewer } = await import("pagedjs");
        if (cancelled) return;
        host.innerHTML = "";
        // paged.js coi string = URL → CSS text phải đưa qua object {key: cssText}.
        // css tài liệu đứng trước, PAGE_CSS sau để khung A4 thắng.
        const flow = await new Previewer().preview(
          safe,
          [{ "doc-style.css": css ?? "", "a4-page.css": PAGE_CSS }],
          host,
        );
        if (!cancelled) setPages(flow.total);
      } catch {
        if (cancelled || !host) return;
        host.innerHTML = safe;
        setPages(0);
      }
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [html, css]);

  return (
    <section data-testid="page-preview" className="flex min-w-0 flex-col gap-2">
      <p className="text-xs text-muted">
        <span data-testid="page-count">{pages > 0 ? pages : "–"}</span> {t("word.pagesUnit")}
      </p>
      <div
        ref={hostRef}
        aria-label={t("word.pagePreviewAria")}
        className="max-h-[75vh] overflow-auto rounded-md border border-border bg-surface-2 p-3"
      />
    </section>
  );
}
