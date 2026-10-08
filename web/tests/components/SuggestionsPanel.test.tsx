import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Suggestion } from "../../src/api/types";
import SuggestionsPanel from "../../src/components/SuggestionsPanel";

const SUGGESTIONS: Suggestion[] = [
  {
    id: 1,
    page_index: 0,
    start: 10,
    end: 15,
    original: "xin chào",
    suggestion: "xin chào",
    reason: "Thiếu dấu",
    status: "pending",
  },
  {
    id: 2,
    page_index: 0,
    start: 30,
    end: 35,
    original: "thế giới",
    suggestion: "thế giới",
    reason: "Sai chính tả",
    status: "pending",
  },
  {
    id: 3,
    page_index: 1,
    start: 5,
    end: 10,
    original: "lỗi OCR",
    suggestion: "lỗi OCR",
    reason: "Ký tự lệch",
    status: "pending",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
});

it("renders empty state when no pending suggestions", () => {
  render(
    <SuggestionsPanel
      suggestions={[]}
      onAccept={vi.fn()}
      onReject={vi.fn()}
      onJump={vi.fn()}
    />,
  );
  expect(screen.getByTestId("suggestions-empty")).toBeInTheDocument();
  expect(screen.queryByTestId("suggestions-panel")).toBeNull();
});

it("renders suggestions grouped by page with original, suggestion, reason", () => {
  render(
    <SuggestionsPanel
      suggestions={SUGGESTIONS}
      onAccept={vi.fn()}
      onReject={vi.fn()}
      onJump={vi.fn()}
    />,
  );
  expect(screen.getByTestId("suggestions-panel")).toBeInTheDocument();
  expect(screen.getByTestId("suggestion-1")).toBeInTheDocument();
  expect(screen.getByTestId("suggestion-2")).toBeInTheDocument();
  expect(screen.getByTestId("suggestion-3")).toBeInTheDocument();
  expect(screen.getByTestId("suggestion-1")).toHaveTextContent("xin chào");
  expect(screen.getByTestId("suggestion-1")).toHaveTextContent("Thiếu dấu");
  expect(screen.getByTestId("suggestion-3")).toHaveTextContent("lỗi OCR");
});

it("calls onAccept when Áp dụng clicked", async () => {
  const onAccept = vi.fn();
  const user = userEvent.setup();
  render(
    <SuggestionsPanel
      suggestions={SUGGESTIONS}
      onAccept={onAccept}
      onReject={vi.fn()}
      onJump={vi.fn()}
    />,
  );
  await user.click(screen.getByTestId("suggestion-accept-1"));
  expect(onAccept).toHaveBeenCalledWith(1);
});

it("calls onReject when Bỏ qua clicked", async () => {
  const onReject = vi.fn();
  const user = userEvent.setup();
  render(
    <SuggestionsPanel
      suggestions={SUGGESTIONS}
      onAccept={vi.fn()}
      onReject={onReject}
      onJump={vi.fn()}
    />,
  );
  await user.click(screen.getByTestId("suggestion-reject-2"));
  expect(onReject).toHaveBeenCalledWith(2);
});

it("calls onJump when suggestion text clicked", async () => {
  const onJump = vi.fn();
  const user = userEvent.setup();
  render(
    <SuggestionsPanel
      suggestions={SUGGESTIONS}
      onAccept={vi.fn()}
      onReject={vi.fn()}
      onJump={onJump}
    />,
  );
  await user.click(screen.getByTestId("suggestion-jump-3"));
  expect(onJump).toHaveBeenCalledWith(SUGGESTIONS[2]);
});

it("filters out non-pending suggestions", () => {
  const mixed: Suggestion[] = [
    ...SUGGESTIONS,
    { ...SUGGESTIONS[0], id: 99, status: "accepted" as const },
  ];
  render(
    <SuggestionsPanel
      suggestions={mixed}
      onAccept={vi.fn()}
      onReject={vi.fn()}
      onJump={vi.fn()}
    />,
  );
  expect(screen.queryByTestId("suggestion-99")).toBeNull();
  expect(screen.getByTestId("suggestion-1")).toBeInTheDocument();
});
