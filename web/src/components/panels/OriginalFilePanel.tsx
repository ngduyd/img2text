import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { ApiError } from "../../api/client";
import { getJobBlob } from "../../lib/blobCache";
import Button from "../ui/Button";
import Card from "../ui/Card";
import Skeleton from "../ui/Skeleton";

/**
 * WS-UI (spec 2026-10-13): ảnh gốc AUTO-FETCH blob khi mount (bỏ toggle
 * "Hiện file"); blob cache module-level theo jobId → 2 section dùng chung,
 * không fetch đôi. Same-origin blob (presigned localhost không tới được).
 */
export default function OriginalFilePanel({
  jobId,
  fileType,
  testid = "panel-original",
}: {
  jobId: string;
  fileType: string;
  testid?: string;
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Revoke URL khi unmount/đổi job; objectURL tạo lại từ cached blob là an toàn.
  useEffect(() => () => {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }, [objectUrl]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    getJobBlob(jobId)
      .then((blob) => {
        if (alive) setObjectUrl(URL.createObjectURL(blob));
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof ApiError ? err.detail : "Tải file thất bại.");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [jobId]);

  const handleDownload = () => {
    if (!objectUrl) return;
    triggerDownload(objectUrl, `job-${jobId}.${downloadExt(fileType)}`);
  };

  return (
    <Card testid={testid} title="File gốc">
      <div className="flex items-center gap-2">
        <Button
          testid="btn-download-original"
          variant="ghost"
          size="sm"
          title="Tải file gốc"
          disabled={!objectUrl}
          onClick={handleDownload}
        >
          <Download aria-hidden="true" className="h-4 w-4" />
          Tải xuống
        </Button>
      </div>
      {error && (
        <p data-testid="original-error" className="mt-2 text-sm text-error">
          {error}
        </p>
      )}
      {loading && <Skeleton testid="original-loading" className="mt-3 h-40" />}
      {objectUrl && !error && (
        <div
          data-testid="original-viewer"
          className="mt-3 max-h-[75vh] overflow-auto"
        >
          {fileType === "image" && (
            <img
              data-testid="original-image"
              src={objectUrl}
              alt="File gốc"
              className="max-w-full rounded-md"
            />
          )}
          {fileType === "pdf" && (
            <iframe
              data-testid="original-pdf-frame"
              src={objectUrl}
              title="File gốc"
              sandbox=""
              className="h-[75vh] w-full rounded-md border border-border"
            />
          )}
          <a
            href={objectUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-block text-sm text-accent-text hover:underline"
          >
            Mở tab mới
          </a>
        </div>
      )}
    </Card>
  );
}

/** Filename extension: pdf vs ảnh fallback (blob type không còn nguồn — cache share). */
function downloadExt(fileType: string): string {
  return fileType === "pdf" ? "pdf" : "jpg";
}

function triggerDownload(href: string, filename: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
