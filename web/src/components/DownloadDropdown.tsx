import { Download } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import Button from "./ui/Button";

/**
 * Lane I Task 5: 1 nút dropdown "Tải xuống" ở header actions (cạnh "Chỉnh
 * sửa") — gộp 4 định dạng text (md|html|docx|pdf) trước đây rải trong
 * ExportBar. R51: testids export-md/export-html/export-docx/export-pdf giữ.
 */
const TEXT_FORMATS = [
  { fmt: "md", testid: "export-md", label: "Tải .md" },
  { fmt: "html", testid: "export-html", label: "Tải .html" },
  { fmt: "docx", testid: "export-docx", label: "Tải .docx" },
  { fmt: "pdf", testid: "export-pdf", label: "Tải .pdf" },
] as const;

export default function DownloadDropdown({
  jobId,
  open,
  onToggle,
}: {
  jobId: string;
  open: boolean;
  onToggle: () => void;
}) {
  const download = async (fmt: (typeof TEXT_FORMATS)[number]["fmt"]) => {
    try {
      const { url } = await api.exportJob(jobId, fmt);
      const w = window.open("", "_blank");
      if (w) w.location = url;
      toast.success("Đã tạo bản xuất.");
    } catch (err) {
      // R59: lỗi download hiển thị toast (header không có inline error slot).
      toast.error(err instanceof ApiError ? err.detail : mapApiError(err));
    }
  };

  return (
    <div className="relative">
      <Button
        testid="btn-download"
        aria-expanded={open}
        aria-controls="download-formats"
        onClick={onToggle}
      >
        <Download className="h-4 w-4" aria-hidden="true" />
        Tải xuống
      </Button>
      <div
        id="download-formats"
        data-testid="download-formats"
        hidden={!open}
        className="absolute right-0 z-20 mt-1 flex w-48 flex-col gap-1 rounded-md border border-border bg-surface p-2 shadow-card"
      >
        {TEXT_FORMATS.map(({ fmt, testid, label }) => (
          <Button
            key={fmt}
            testid={testid}
            variant="secondary"
            size="sm"
            onClick={() => void download(fmt)}
          >
            {label}
          </Button>
        ))}
      </div>
    </div>
  );
}
