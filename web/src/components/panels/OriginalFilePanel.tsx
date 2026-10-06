import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { ApiError, api } from "../../api/client";
import Button from "../ui/Button";
import Card from "../ui/Card";
import Skeleton from "../ui/Skeleton";

/**
 * Plan V (V2): inline original viewer + download via SAME-ORIGIN blob.
 * Presigned localhost:4566 URLs unreachable via VSCode port-forward —
 * server now streams bytes; blob → objectURL for <img>/<iframe>/download.
 * Lazy (Task 2 contract kept): blob fetched only on first expand.
 */
export default function OriginalFilePanel({
  jobId,
  fileType,
}: {
  jobId: string;
  fileType: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Revoke the replaced blob URL; revoke current one on unmount (no leak).
  useEffect(() => () => {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }, [objectUrl]);

  const toggle = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (objectUrl || loading) return; // already fetched → just re-open
    setLoading(true);
    setError(null);
    try {
      const blob = await api.downloadJobFile(jobId);
      setObjectUrl(URL.createObjectURL(blob));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Tải file thất bại.");
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    // Reuse viewer blob when loaded; otherwise fetch → anchor → revoke.
    if (objectUrl) {
      triggerDownload(objectUrl, `job-${jobId}`);
      return;
    }
    try {
      const blob = await api.downloadJobFile(jobId);
      const href = URL.createObjectURL(blob);
      triggerDownload(href, `job-${jobId}`);
      URL.revokeObjectURL(href);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Tải file thất bại.");
    }
  };

  return (
    <Card testid="panel-original" title="File gốc">
      <div className="flex items-center gap-2">
        <Button
          testid="toggle-original"
          variant="secondary"
          size="sm"
          aria-expanded={expanded}
          onClick={toggle}
        >
          {expanded ? "Ẩn file" : "Hiện file"}
        </Button>
        <Button
          testid="btn-download-original"
          variant="ghost"
          size="sm"
          title="Tải file gốc"
          disabled={loading}
          onClick={handleDownload}
        >
          <Download aria-hidden="true" className="h-4 w-4" />
          Tải xuống
        </Button>
      </div>
      {expanded && (
        <div className="mt-3">
          {loading && (
            <Skeleton testid="original-loading" className="h-40" />
          )}
          {error && (
            <p data-testid="original-error" className="text-sm text-error">
              {error}
            </p>
          )}
          {objectUrl && !error && (
            <>
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
                  className="h-96 w-full rounded-md border border-border"
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
            </>
          )}
        </div>
      )}
    </Card>
  );
}

function triggerDownload(href: string, filename: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
