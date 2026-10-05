import { useState } from "react";
import { ApiError, api } from "../../api/client";
import Button from "../ui/Button";
import Card from "../ui/Card";

/**
 * Task 2: lazy file viewer — signed URL fetched only on first expand
 * (collapsed default keeps /file off the network until asked).
 */
export default function OriginalFilePanel({
  jobId,
  fileType,
}: {
  jobId: string;
  fileType: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (url || loading) return; // already fetched → just re-open
    setLoading(true);
    setError(null);
    try {
      const res = await api.getJobFile(jobId);
      setUrl(res.url);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Tải file thất bại.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card testid="panel-original" title="File gốc">
      <Button
        testid="toggle-original"
        variant="secondary"
        size="sm"
        aria-expanded={expanded}
        onClick={toggle}
      >
        {expanded ? "Ẩn file" : "Hiện file"}
      </Button>
      {expanded && (
        <div className="mt-3">
          {loading && (
            <div
              data-testid="original-loading"
              aria-busy="true"
              className="h-40 animate-pulse rounded-lg bg-border/40"
            />
          )}
          {error && (
            <p data-testid="original-error" className="text-sm text-error">
              {error}
            </p>
          )}
          {url && !error && (
            <>
              {fileType === "image" && (
                <img
                  src={url}
                  alt="File gốc"
                  className="max-w-full rounded-lg"
                />
              )}
              {fileType === "pdf" && (
                <iframe
                  src={url}
                  title="File gốc PDF"
                  className="h-96 w-full rounded-lg border border-border"
                />
              )}
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-sm text-accent"
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
