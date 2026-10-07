import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { ReactElement } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../src/api/client";
import MarkdownEditor from "../../src/components/MarkdownEditor";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      patchContent: vi.fn(),
    },
  };
});

let queryClient: QueryClient;

/**
 * JD2: `editing` controlled by the host (JobDetail btn-edit-doc = single edit
 * entry) — harness passes the controlled pair so tests drive the same state
 * the page does. MarkdownEditor has no edit button anymore (R51 exception:
 * user "1 chỗ thôi").
 */
function Harness({
  initial = "## Part 2",
  editing = false,
}: {
  initial?: string;
  editing?: boolean;
}) {
  const [isEditing, setEditing] = useState(editing);
  return (
    <MarkdownEditor
      jobId="5"
      initial={initial}
      editing={isEditing}
      onEditingChange={setEditing}
    />
  );
}

/** Provider wraps like the App shell (R30). */
function renderEditor(ui: ReactElement) {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

/** R51 exception: btn-edit removed per user "1 chỗ thôi" — preview + hint instead. */
it("not editing: no btn-edit, shows source preview + hint (single entry = btn-edit-doc)", () => {
  renderEditor(<Harness />);
  expect(screen.queryByTestId("btn-edit")).toBeNull();
  expect(screen.queryByTestId("textarea-markdown")).toBeNull();
  expect(screen.getByTestId("md-source-preview")).toHaveTextContent("## Part 2");
  expect(screen.getByTestId("md-edit-hint")).toHaveTextContent(
    "Nhấn Edit ở trên để sửa nội dung.",
  );
});

it("editing: save calls patchContent and closes editing", async () => {
  vi.mocked(api.patchContent).mockResolvedValue({});
  renderEditor(<Harness editing />);
  const ta = screen.getByTestId("textarea-markdown") as HTMLTextAreaElement;
  expect(ta.value).toBe("## Part 2");
  const user = userEvent.setup();
  await user.clear(ta);
  await user.type(ta, "# Đã sửa");
  await user.click(screen.getByTestId("btn-save"));
  expect(api.patchContent).toHaveBeenCalledWith("5", "# Đã sửa");
  await waitFor(() => expect(screen.queryByTestId("textarea-markdown")).toBeNull());
  // Closed → preview + hint back, no edit button.
  expect(screen.queryByTestId("btn-edit")).toBeNull();
  expect(screen.getByTestId("md-edit-hint")).toBeInTheDocument();
});

it("shows ApiError detail on save failure and keeps edit open", async () => {
  vi.mocked(api.patchContent).mockRejectedValue(new ApiError("Nội dung quá lớn."));
  renderEditor(<Harness editing />);
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-save"));
  expect(await screen.findByTestId("editor-error")).toHaveTextContent(
    "Nội dung quá lớn.",
  );
  // Edit NOT lost on error: textarea stays open with typed content.
  expect(screen.getByTestId("textarea-markdown")).toHaveValue("## Part 2");
});

it("successful save invalidates job query (binding, T5 ledger)", async () => {
  vi.mocked(api.patchContent).mockResolvedValue({});
  renderEditor(<Harness editing />);
  const spy = vi.spyOn(queryClient, "invalidateQueries");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-save"));
  await waitFor(() =>
    expect(spy).toHaveBeenCalledWith({ queryKey: ["job", "5"] }),
  );
});

/** JD2 wiring: md-tb-* → applyMdOp → textarea value + selection (rAF sau render). */
it("MdToolbar bold wraps selection, restores cursor, no PATCH until save", async () => {
  renderEditor(<Harness initial="# A" editing />);
  const user = userEvent.setup();
  const ta = screen.getByTestId("textarea-markdown") as HTMLTextAreaElement;
  expect(ta.value).toBe("# A");
  ta.setSelectionRange(0, ta.value.length);
  await user.click(screen.getByTestId("md-tb-bold"));
  await waitFor(() => expect(ta).toHaveValue("**# A**"));
  await waitFor(() => {
    expect(ta.selectionStart).toBe(2);
    expect(ta.selectionEnd).toBe(5);
  });
  expect(api.patchContent).not.toHaveBeenCalled();
  // toggle: bọc lần 2 → gỡ marker
  await user.click(screen.getByTestId("md-tb-bold"));
  await waitFor(() => expect(ta).toHaveValue("# A"));
});

it("toolbar renders only while editing (btn-edit-doc path sees md-tb-*)", async () => {
  renderEditor(<Harness />);
  expect(screen.queryByRole("toolbar", { name: "Công cụ Markdown" })).toBeNull();
  renderEditor(<Harness editing />);
  expect(screen.getByRole("toolbar", { name: "Công cụ Markdown" })).toBeInTheDocument();
  expect(screen.getByTestId("md-tb-undo")).toBeInTheDocument();
});
