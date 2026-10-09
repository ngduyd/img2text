import { Sparkles } from "lucide-react";
import type { Suggestion } from "../api/types";
import Button from "./ui/Button";

/**
 * Plan proofread: panel DƯỚI editor — mỗi dòng = phrase → suggestion + reason,
 * click dòng = jump tới vị trí; nút Áp dụng / Bỏ qua. User quyết định.
 */
export default function SuggestionsPanel({
  suggestions,
  onAccept,
  onReject,
  onJump,
}: {
  suggestions: Suggestion[];
  onAccept: (sid: number) => void;
  onReject: (sid: number) => void;
  onJump: (suggestion: Suggestion) => void;
}) {
  const pending = suggestions.filter((s) => s.status === "pending");

  if (pending.length === 0) {
    return (
      <div
        data-testid="suggestions-empty"
        className="flex flex-col items-center gap-2 rounded-md border border-border bg-surface-2 p-4 text-center"
      >
        <Sparkles className="h-5 w-5 text-muted" aria-hidden="true" />
        <p className="text-sm font-medium">Không có gợi ý nào.</p>
        <p className="text-xs text-muted">OCR chưa phát hiện lỗi nào cần sửa.</p>
      </div>
    );
  }

  const pages: { page: number; items: Suggestion[] }[] = [];
  for (const s of pending) {
    let group = pages.find((g) => g.page === s.page_index);
    if (!group) {
      group = { page: s.page_index, items: [] };
      pages.push(group);
    }
    group.items.push(s);
  }

  return (
    <div data-testid="suggestions-panel" className="flex flex-col gap-3">
      {pages.map((group) => (
        <div key={group.page} className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Trang {group.page + 1}
          </h3>
          {group.items.map((s) => (
            <article
              key={s.id}
              data-testid={`suggestion-${s.id}`}
              className="rounded-md border border-border bg-surface-2 p-3"
            >
              <button
                type="button"
                data-testid={`suggestion-jump-${s.id}`}
                onClick={() => onJump(s)}
                className="flex w-full cursor-pointer flex-col items-baseline gap-1 text-left transition duration-150 ease-out hover:opacity-80"
              >
                <span className="flex items-baseline gap-2">
                  <span className="text-sm line-through decoration-error text-error">
                    {s.original}
                  </span>
                  <span className="text-sm text-success">{s.suggestion}</span>
                </span>
                <span className="text-xs text-muted">{s.reason}</span>
              </button>
              <div className="mt-2 flex gap-2">
                <Button
                  testid={`suggestion-accept-${s.id}`}
                  variant="primary"
                  size="sm"
                  onClick={() => onAccept(s.id)}
                >
                  Áp dụng
                </Button>
                <Button
                  testid={`suggestion-reject-${s.id}`}
                  variant="ghost"
                  size="sm"
                  onClick={() => onReject(s.id)}
                >
                  Bỏ qua
                </Button>
              </div>
            </article>
          ))}
        </div>
      ))}
    </div>
  );
}
