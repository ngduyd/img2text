import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import Dropzone from "../../src/components/Dropzone";

// R2 presigned upload (REAL client api): stubbed fetch (presign/create) +
// fake XMLHttpRequest cho POST form → storage (upload.onprogress).

vi.mock("../../src/lib/pdfjs", () => ({ loadPdf: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const PRESIGN = {
  storage_key: `uploads/${"ab".repeat(32)}.txt`,
  url: "https://r2.example/bucket",
  fields: { key: `uploads/${"ab".repeat(32)}.txt`, "Content-Type": "text/plain", policy: "fake-policy-b64" },
  max_bytes: 52428800,
};

let sentXhr: {
  form: FormData | null;
  upload: { onprogress: ((e: ProgressEvent) => void) | null };
  onload: (() => void) | null;
} | null = null;

class FakeXHR {
  upload = { onprogress: null as ((e: ProgressEvent) => void) | null };
  status = 200;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  open() {}
  send(form: FormData) {
    sentXhr = { form, upload: this.upload, onload: () => this.onload?.() };
  }
}

function renderDropzone(onUploaded = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Dropzone onUploaded={onUploaded} onFormatChange={vi.fn()} />
    </QueryClientProvider>,
  );
  return { onUploaded };
}

it("drop → progress bar follows XHR onprogress; upload done → bar ẩn + pdf.js count", async () => {
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  // create bị "treo" cho tới khi test resolve → bước đếm trang quan sát được
  let resolveCreate!: (r: Response) => void;
  const createPromise = new Promise<Response>((res) => (resolveCreate = res));
  const createBodies: unknown[] = [];
  const fetchSpy = vi.fn(async (url: string, opts?: { method?: string; body?: string }) => {
    if (String(url) === "/api/jobs" && opts?.method === "POST") {
      createBodies.push(JSON.parse(opts.body ?? "{}"));
      return createPromise;
    }
    const body =
      url === "/api/auth/me"
        ? { id: 1, role: "user", ocr_enabled: true }
        : PRESIGN;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchSpy);

  const { onUploaded } = renderDropzone();
  await screen.findByTestId("btn-upload");
  const file = new File(["x"], "a.txt", { type: "text/plain" });
  fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [file] } });

  // presign (fetch) → POST form thẳng tới storage qua XHR (không qua backend)
  await vi.waitFor(() => expect(sentXhr).not.toBeNull());
  expect(sentXhr!.form!.get("key")).toBe(PRESIGN.storage_key);
  expect((sentXhr!.form!.get("file") as File).name).toBe("a.txt");
  expect(sentXhr!.form!.get("policy")).toBe("fake-policy-b64");

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
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith({ id: 42, status: "queued" }));
  // create = metadata-only (storage_key + page_count; txt = 1)
  expect(createBodies).toEqual([
    { storage_key: PRESIGN.storage_key, page_count: 1, output_format: "md", mode: "layout" },
  ]);
  // create xong → phase idle: chữ đếm trang biến mất
  await waitFor(() => expect(screen.queryByTestId("upload-counting")).not.toBeInTheDocument());
});
