import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { toast } from "sonner";
import { expect, it, vi } from "vitest";
import Jobs from "../../src/pages/Jobs";

// Port của Dropzone.upload.test (Dropzone đã xóa — spec U4): R2 presigned upload
// (REAL client api): stubbed fetch (me/list/presign/create) + fake XMLHttpRequest
// cho PUT ArrayBuffer → storage (upload.onprogress) + pdf.js đếm trang.

vi.mock("../../src/lib/pdfjs", () => ({
  loadPdf: vi.fn(async () => ({ numPages: 3, getPage: vi.fn() })),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => vi.fn() };
});

const PRESIGN = {
  storage_key: `uploads/${"ab".repeat(32)}.pdf`,
  url: "https://r2.example/bucket/uploads/ab.pdf",
  max_bytes: 52428800,
};

const QUOTA = {
  daily_limit: 25,
  daily_used: 15,
  weekly_limit: 150,
  weekly_used: 45,
  daily_remaining: 10,
  weekly_remaining: 105,
};

let sentXhr: {
  method: string;
  url: string;
  body: unknown;
  upload: { onprogress: ((e: ProgressEvent) => void) | null };
  onload: (() => void) | null;
} | null = null;

class FakeXHR {
  upload = { onprogress: null as ((e: ProgressEvent) => void) | null };
  status = 200;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  open(method: string, url: string) {
    sentXhr = { method, url, body: null, upload: this.upload, onload: () => this.onload?.() };
  }
  send(body: unknown) {
    if (sentXhr) sentXhr.body = body;
  }
}

// PNG 1×1 thật — pdf-lib từ chối bytes giả ("The input is not a PNG file!").
const PNG_1PX = Uint8Array.from(
  atob(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  ),
  (c) => c.charCodeAt(0),
);

function renderJobs() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={["/jobs"]}>
        <Jobs />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("Gửi → presign → XHR progress → pdf.js count → metadata-only create", async () => {
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  Object.defineProperty(URL, "createObjectURL", {
    value: vi.fn(() => "blob:mock"),
    configurable: true,
    writable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true, writable: true });
  // create bị "treo" cho tới khi test resolve → bước đếm trang quan sát được
  let resolveCreate!: (r: Response) => void;
  const createPromise = new Promise<Response>((res) => (resolveCreate = res));
  const createBodies: unknown[] = [];
  const fetchSpy = vi.fn(async (url: string, opts?: { method?: string; body?: string }) => {
    if (String(url) === "/api/jobs" && opts?.method === "POST") {
      createBodies.push(JSON.parse(opts.body ?? "{}"));
      return createPromise;
    }
    const url_ = String(url);
    const body = url_ === "/api/quota/me"
      ? QUOTA
      : url_.startsWith("/api/auth/me")
      ? { id: 1, role: "user", ocr_enabled: true }
      : String(url).startsWith("/api/jobs?")
        ? { items: [], total: 0, page: 1, page_size: 10 }
        : PRESIGN;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchSpy);

  renderJobs();
  fireEvent.change(screen.getByTestId("muf-input"), {
    target: { files: [new File([PNG_1PX], "photo.png", { type: "image/png" })] },
  });
  await screen.findByTestId("muf-card-0");
  fireEvent.click(screen.getByTestId("muf-submit"));
  await screen.findByTestId("submit-modal");
  fireEvent.click(screen.getByTestId("sm-confirm"));

  // presign (fetch) → PUT ArrayBuffer thẳng tới storage qua XHR (không qua backend)
  await vi.waitFor(() => expect(sentXhr).not.toBeNull());
  expect(sentXhr!.method).toBe("PUT");
  expect(sentXhr!.url).toBe(PRESIGN.url);
  expect(sentXhr!.body).toBeInstanceOf(ArrayBuffer);

  // progress bar hiện 0% → onprogress 42% → percent cập nhật
  expect(screen.getByTestId("upload-progress")).toBeInTheDocument();
  act(() => {
    sentXhr!.upload.onprogress?.({ loaded: 42, total: 100, lengthComputable: true } as ProgressEvent);
  });
  expect(screen.getByTestId("upload-progress")).toHaveTextContent("42%");

  // upload done → bar ẩn → bước đếm trang (indeterminate, create còn pending)
  act(() => sentXhr!.onload?.());
  await waitFor(() => expect(screen.queryByTestId("upload-progress")).not.toBeInTheDocument());
  expect(screen.getByTestId("upload-counting")).toHaveTextContent("Đang đếm trang...");

  resolveCreate(new Response(JSON.stringify({ id: 42, status: "queued" }), { status: 201 }));
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Đã tải lên — đang chờ xử lý."));
  // Lane B Task 5: 1 ảnh → upload THÔ (giữ đuôi .png + content_type match magic-byte
  // Lane A sniff); image luôn page_count 1 (pdf.js chỉ đếm PDF).
  expect(createBodies).toEqual([
    {
      storage_key: PRESIGN.storage_key,
      page_count: 1,
      output_format: "md",
      mode: "layout",
      filename: "photo.png",
    },
  ]);
  // create xong → phase idle: chữ đếm trang biến mất
  await waitFor(() => expect(screen.queryByTestId("upload-counting")).not.toBeInTheDocument());
  // T6: badge quota trong Jobs header + invalidate sau khi tạo job → refetch
  expect(screen.getByTestId("quota-remaining")).toHaveTextContent("Còn 10/25 trang hôm nay");
  expect(screen.getByTestId("quota-remaining")).toHaveTextContent("105/150 trang tuần này");
  await waitFor(() =>
    expect(fetchSpy.mock.calls.filter((c) => String(c[0]) === "/api/quota/me").length).toBeGreaterThan(1),
  );
});
