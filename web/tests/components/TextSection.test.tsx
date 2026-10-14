import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
import type { RegionOut, Suggestion } from "../../src/api/types";
import TextSection from "../../src/components/TextSection";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getExtraction: vi.fn(),
      getSuggestions: vi.fn(),
      saveExtraction: vi.fn(),
      rejectSuggestion: vi.fn(),
      getCropUrl: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderSection(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const SUGGESTION: Suggestion = {
  id: 11,
  page_index: 0,
  start: 4,
  end: 9,
  original: "chao",
  suggestion: "chào",
  reason: "thiếu dấu",
  status: "pending",
};

const REGIONS: RegionOut[] = [
  { id: "p1r0", bbox: [1, 2, 3, 4], text: "", verdict: "image_unextractable", placeholder: true },
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getExtraction).mockResolvedValue({
    text: "Xin chao ban",
    text_version: 3,
  });
  vi.mocked(api.getSuggestions).mockResolvedValue([SUGGESTION]);
  vi.mocked(api.getCropUrl).mockResolvedValue({ url: "https://r2/c.jpg" });
});

// --- Lane I Task 1: toggle "Soạn thảo" (Tiptap thuần text) + paste strip ---

it("toggle Soạn thảo → text editor; toggle off → article again", async () => {
  const user = userEvent.setup();
  renderSection(<TextSection jobId="5" />);
  expect(await screen.findByTestId("extraction-text")).toBeInTheDocument();
  const btn = screen.getByTestId("btn-edit-text");
  expect(btn).toHaveAttribute("aria-pressed", "false");
  await user.click(btn);
  expect(btn).toHaveAttribute("aria-pressed", "true");
  const editor = await screen.findByTestId("text-editor");
  await waitFor(() =>
    expect(editor.querySelector(".ProseMirror")).toHaveAttribute("contenteditable", "true"),
  );
  expect(screen.queryByTestId("extraction-text")).not.toBeInTheDocument();
  await user.click(btn);
  expect(screen.queryByTestId("text-editor")).not.toBeInTheDocument();
  expect(screen.getByTestId("extraction-text")).toBeInTheDocument();
});

it("paste strip: dán Word (html + plain) → chỉ giữ plain text + xuống dòng", async () => {
  const user = userEvent.setup();
  renderSection(<TextSection jobId="5" />);
  await screen.findByTestId("extraction-text");
  await user.click(screen.getByTestId("btn-edit-text"));
  const editor = await screen.findByTestId("text-editor");
  const pm = editor.querySelector(".ProseMirror") as HTMLElement;
  await waitFor(() => expect(pm).toHaveAttribute("contenteditable", "true"));
  pm.focus();
  fireEvent.paste(pm, {
    clipboardData: {
      getData: (type: string) =>
        type === "text/plain" ? "Dong mot\nDong hai" : "<b><i>Word rác</i></b>",
    },
  });
  await waitFor(() => expect(pm).toHaveTextContent("Dong mot"));
  expect(pm).toHaveTextContent("Dong hai");
  expect(pm.querySelector("strong")).toBeNull();
  expect(pm.querySelector("em")).toBeNull();
});

// --- Review r1 P2a/P2b/P2f: blank lines round-trip + aria-label + empty-plain paste ---

it("review r1 P2a: editor giữ empty lines — save round-trip text giữ \\n\\n", async () => {
  vi.mocked(api.getExtraction).mockResolvedValue({
    text: "Dòng 1\n\nDòng 3",
    text_version: 3,
  });
  vi.mocked(api.saveExtraction).mockResolvedValue({
    synced: { md: false, docx: false },
    needs_render: [],
    text_version: 4,
    requires_rerender: false,
  });
  const user = userEvent.setup();
  renderSection(<TextSection jobId="5" />);
  await screen.findByTestId("extraction-text");
  await user.click(screen.getByTestId("btn-edit-text"));
  await screen.findByTestId("text-editor");
  await user.click(screen.getByTestId("btn-save-text"));
  await waitFor(() => expect(api.saveExtraction).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.saveExtraction).mock.calls[0][1].text).toBe("Dòng 1\n\nDòng 3");
});

it("review r1 P2b: text editor Tiptap có aria-label trên contenteditable", async () => {
  renderSection(<TextSection jobId="5" />);
  await screen.findByTestId("extraction-text");
  await userEvent.click(screen.getByTestId("btn-edit-text"));
  const editor = await screen.findByTestId("text-editor");
  const pm = editor.querySelector(".ProseMirror") as HTMLElement;
  await waitFor(() =>
    expect(pm).toHaveAttribute("aria-label", "Edit text"),
  );
});

it("review r1 P2f: paste text/plain rỗng → preventDefault, không rơi về HTML", async () => {
  renderSection(<TextSection jobId="5" />);
  await screen.findByTestId("extraction-text");
  await userEvent.click(screen.getByTestId("btn-edit-text"));
  const editor = await screen.findByTestId("text-editor");
  const pm = editor.querySelector(".ProseMirror") as HTMLElement;
  await waitFor(() => expect(pm).toHaveAttribute("contenteditable", "true"));
  pm.focus();
  const notPrevented = fireEvent.paste(pm, {
    clipboardData: {
      getData: (type: string) => (type === "text/plain" ? "" : "<b>Word rác</b>"),
    },
  });
  // preventDefault luôn chạy (không rơi về default HTML paste) + chèn "".
  expect(notPrevented).toBe(false);
  expect(pm.querySelector("b")).toBeNull();
  expect(pm.textContent).not.toContain("Word rác");
});

it("btn-save-text → saveExtraction full text (không old/new phrase) + toast", async () => {
  const user = userEvent.setup();
  vi.mocked(api.saveExtraction).mockResolvedValue({
    synced: { md: false, docx: false },
    needs_render: [],
    text_version: 4,
    requires_rerender: false,
  });
  const { toast } = await import("sonner");
  renderSection(<TextSection jobId="5" />); // text "Xin chao ban", version 3
  await screen.findByTestId("extraction-text");
  await user.click(screen.getByTestId("btn-edit-text"));
  const editor = await screen.findByTestId("text-editor");
  const pm = editor.querySelector(".ProseMirror") as HTMLElement;
  await waitFor(() => expect(pm).toHaveAttribute("contenteditable", "true"));
  pm.focus();
  fireEvent.paste(pm, {
    clipboardData: { getData: () => "Dòng mới" },
  });
  await waitFor(() => expect(pm).toHaveTextContent("Dòng mới"));
  await user.click(screen.getByTestId("btn-save-text"));
  await waitFor(() => expect(api.saveExtraction).toHaveBeenCalledTimes(1));
  const [, body] = vi.mocked(api.saveExtraction).mock.calls[0];
  expect(body.text).toContain("Dòng mới");
  expect(body.expected_text_version).toBe(3);
  expect(body).not.toHaveProperty("old_phrase");
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Saved."));
});

it("renders issues panel below text when regions provided", async () => {
  renderSection(<TextSection jobId="5" regions={REGIONS} fileType="image" />);
  expect(await screen.findByTestId("extraction-text")).toBeInTheDocument();
  expect(screen.getByTestId("issues-toggle")).toBeInTheDocument();
});

it("no regions (extraction page) → no issues panel", async () => {
  renderSection(<TextSection jobId="5" />);
  expect(await screen.findByTestId("extraction-text")).toBeInTheDocument();
  expect(screen.queryByTestId("issues-toggle")).toBeNull();
});

// P2-3 review r1: fileType unknown (không prop) → KHÔNG fetch crop (không default "image").
it("regions without fileType → no crop fetch", async () => {
  renderSection(<TextSection jobId="5" regions={REGIONS} />);
  expect(await screen.findByTestId("issues-toggle")).toBeInTheDocument();
  expect(await screen.findByTestId("issue-p1r0")).toBeInTheDocument();
  expect(api.getCropUrl).not.toHaveBeenCalled();
});

it("Sửa khác… custom input → saveExtraction with custom phrase", async () => {
  const user = userEvent.setup();
  vi.mocked(api.saveExtraction).mockResolvedValue({
    synced: { md: true, docx: true },
    needs_render: [],
    text_version: 4,
    requires_rerender: false,
  });
  renderSection(<TextSection jobId="5" />);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  const input = screen.getByTestId("input-custom-11") as HTMLInputElement;
  await user.type(input, "xin chào");
  await user.click(screen.getByTestId("btn-save-custom-11"));
  await waitFor(() => expect(api.saveExtraction).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.saveExtraction).mock.calls[0]).toEqual([
    "5",
    {
      text: "Xin xin chào ban",
      old_phrase: "chao",
      new_phrase: "xin chào",
      expected_text_version: 3,
    },
  ]);
});

// P2-5 review r1: bấm Lưu khi rỗng → lỗi role="alert" + aria-describedby (button phải bấm được).
it("empty custom text → Lưu shows alert error + aria-describedby, không save", async () => {
  renderSection(<TextSection jobId="5" />);
  const user = userEvent.setup();
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  const input = screen.getByTestId("input-custom-11");
  expect(screen.queryByTestId("custom-error-11")).toBeNull();
  await user.click(screen.getByTestId("btn-save-custom-11"));
  const err = await screen.findByTestId("custom-error-11");
  expect(err).toHaveAttribute("role", "alert");
  expect(input).toHaveAttribute("aria-describedby", "custom-error-11");
  expect(api.saveExtraction).not.toHaveBeenCalled();
  // gõ text → lỗi biến mất
  await user.type(input, "a");
  expect(screen.queryByTestId("custom-error-11")).toBeNull();
});

// --- Task 6: confirm modal queue (requires_rerender → "Lưu & xếp hàng") ---

it("save with requires_rerender → confirm modal; Lưu & xếp hàng → toast + invalidate", async () => {
  const user = userEvent.setup();
  vi.mocked(api.saveExtraction).mockResolvedValue({
    synced: { md: true, docx: true },
    needs_render: [],
    text_version: 4,
    requires_rerender: true,
  });
  const { toast } = await import("sonner");
  const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const spy = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <TextSection jobId="5" />
    </QueryClientProvider>,
  );
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  await user.click(screen.getByTestId("btn-apply-11"));
  const modal = await screen.findByTestId("rerender-modal");
  expect(modal).toHaveTextContent("Saving the text requires a layout rebuild. Add to the rebuild queue?");
  await user.click(screen.getByTestId("btn-rerender-confirm"));
  await waitFor(() =>
    expect(toast.success).toHaveBeenCalledWith("Layout rebuild queued."),
  );
  await waitFor(() =>
    expect(spy).toHaveBeenCalledWith({ queryKey: ["job", "5"] }),
  );
  expect(screen.queryByTestId("rerender-modal")).not.toBeInTheDocument();
});

it("requires_rerender modal: Hủy closes without queue toast", async () => {
  const user = userEvent.setup();
  vi.mocked(api.saveExtraction).mockResolvedValue({
    synced: { md: true, docx: true },
    needs_render: [],
    text_version: 4,
    requires_rerender: true,
  });
  const { toast } = await import("sonner");
  renderSection(<TextSection jobId="5" />);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  await user.click(screen.getByTestId("btn-apply-11"));
  await user.click(await screen.findByTestId("btn-rerender-cancel"));
  expect(screen.queryByTestId("rerender-modal")).not.toBeInTheDocument();
  expect(toast.success).not.toHaveBeenCalledWith("Layout rebuild queued.");
});
