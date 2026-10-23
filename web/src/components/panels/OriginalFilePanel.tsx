import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { getJobBlob } from "../../lib/blobCache";
import { useT } from "../../i18n";
import { mapApiError } from "../../lib/errors";
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
  bare = false,
}: {
  jobId: string;
  fileType: string;
  testid?: string;
  bare?: boolean;
}) {
  const { t } = useT();
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
        // 410 = file đã purge → thông báo thân thiện thay vì "HTTP 410".
        if (alive) setError(mapApiError(err));
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
    <Card testid={testid} title={t("jd.originalFile")} bare={bare}>
      <div className="flex items-center gap-2">
        <Button
          testid="btn-download-original"
          variant="ghost"
          size="sm"
          title={t("jd.downloadOriginal")}
          disabled={!objectUrl}
          onClick={handleDownload}
        >
          <Download aria-hidden="true" className="h-4 w-4" />
          {t("jd.download")}
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
              alt={t("jd.originalFile")}
              className="max-w-full rounded-md"
            />
          )}
          {fileType === "pdf" && (
            <iframe
              data-testid="original-pdf-frame"
              src={objectUrl}
              title={t("jd.originalFile")}
              // Wave-3: KHÔNG sandbox — blob URL same-origin, sandbox "" chặn
              // browser PDF viewer built-in (trắng).
              className="h-[75vh] w-full rounded-md border border-border"
            />
          )}
          <a
            href={objectUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-block text-sm text-accent-text hover:underline"
          >
            {t("jd.openNewTab")}
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
