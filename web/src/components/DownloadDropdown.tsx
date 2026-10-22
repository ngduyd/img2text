import { Download } from "lucide-react";
import { useEffect } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import { useT } from "../i18n";
import Button from "./ui/Button";

/**
 * Lane I Task 5: 1 nút dropdown "Tải xuống" ở header actions (cạnh "Chỉnh
 * sửa") — gộp 4 định dạng text (md|html|docx|pdf) trước đây rải trong
 * ExportBar. R51: testids export-md/export-html/export-docx/export-pdf giữ.
 */
const TEXT_FORMATS = [
  { fmt: "md", testid: "export-md", labelKey: "export.fmtMd" },
  { fmt: "html", testid: "export-html", labelKey: "export.fmtHtml" },
  { fmt: "docx", testid: "export-docx", labelKey: "export.fmtDocx" },
  { fmt: "pdf", testid: "export-pdf", labelKey: "export.fmtPdf" },
] as const;

/** Layout exports (bản dựng layout) — trước đây nằm trong ExportBar riêng. */
const LAYOUT_FORMATS = [
  { fmt: "md-layout", testid: "btn-export-md-layout", labelKey: "export.mdLayout" },
  { fmt: "docx-layout", testid: "btn-export-docx-layout", labelKey: "export.docxLayout" },
] as const;

export default function DownloadDropdown({
  jobId,
  open,
  onToggle,
  layoutReady = false,
}: {
  jobId: string;
  open: boolean;
  onToggle: () => void;
  /** Job chưa dựng layout → ẩn nhóm md-layout/docx-layout. */
  layoutReady?: boolean;
}) {
  const { t } = useT();
  const download = async (fmt: string) => {
    try {
      const { url } = await api.exportJob(jobId, fmt);
      const w = window.open("", "_blank");
      if (w) w.location = url;
      toast.success(t("export.created"));
    } catch (err) {
      // R59: lỗi download hiển thị toast (header không có inline error slot).
      toast.error(err instanceof ApiError ? err.detail : mapApiError(err));
    }
  };

  // Review r1 P2c: Escape đóng dropdown (a11y menu pattern).
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onToggle();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onToggle]);

  return (
    <div className="relative">
      <Button
        testid="btn-download"
        aria-expanded={open}
        aria-haspopup="true"
        aria-controls="download-formats"
        onClick={onToggle}
      >
        <Download className="h-4 w-4" aria-hidden="true" />
        {t("jd.download")}
      </Button>
      <div
        id="download-formats"
        data-testid="download-formats"
        hidden={!open}
        className="absolute right-0 z-20 mt-1 flex w-48 flex-col gap-1 rounded-md border border-border bg-surface p-2 shadow-card"
      >
        {layoutReady && (
          <>
            <p className="px-1 pt-1 text-xs font-medium uppercase tracking-wide text-muted">
              {t("export.layoutGroup")}
            </p>
            {LAYOUT_FORMATS.map(({ fmt, testid, labelKey }) => (
              <Button
                key={fmt}
                testid={testid}
                variant="secondary"
                size="sm"
                onClick={() => {
                  void download(fmt);
                  if (open) onToggle();
                }}
              >
                {t(labelKey)}
              </Button>
            ))}
          </>
        )}
        <p className="px-1 pt-1 text-xs font-medium uppercase tracking-wide text-muted">
          {t("export.textGroup")}
        </p>
        {TEXT_FORMATS.map(({ fmt, testid, labelKey }) => (
          <Button
            key={fmt}
            testid={testid}
            variant="secondary"
            size="sm"
            // Review r1 P2c: close-on-select (chọn item → đóng dropdown).
            onClick={() => {
              void download(fmt);
              if (open) onToggle();
            }}
          >
            {t(labelKey)}
          </Button>
        ))}
      </div>
    </div>
  );
}
