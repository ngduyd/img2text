import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import MultiFileUpload from "../../src/components/MultiFileUpload";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// jsdom thiếu object URL cho <img src> thumbnail.
beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(URL, "createObjectURL", {
    value: vi.fn(() => "blob:x"),
    configurable: true,
    writable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true, writable: true });
});

const img = (n: string) => new File(["x"], n, { type: "image/png" });

function add(files: File[]) {
  fireEvent.change(screen.getByTestId("muf-input"), { target: { files } });
}

it("empty state: 'Tải file lên' + 'Kéo thả file vào'; thêm N file → N cards", () => {
  render(<MultiFileUpload onSubmit={vi.fn()} />);
  expect(screen.getByText("Tải file lên")).toBeInTheDocument();
  expect(screen.getByText(/Kéo thả file vào/)).toBeInTheDocument();
  add([img("a.png"), img("b.png"), img("c.png")]);
  expect(screen.getAllByTestId(/muf-card-/)).toHaveLength(3);
});

it("Xóa xóa đúng card", () => {
  render(<MultiFileUpload onSubmit={vi.fn()} />);
  add([img("a.png"), img("b.png")]);
  fireEvent.click(screen.getByTestId("muf-remove-0"));
  expect(screen.getAllByTestId(/muf-card-/)).toHaveLength(1);
  expect(screen.getByText("b.png")).toBeInTheDocument();
});

it("quá 25 trang → chặn + toast.error, giữ 25 card", () => {
  render(<MultiFileUpload onSubmit={vi.fn()} />);
  add(Array.from({ length: 26 }, (_, i) => img(`${i}.png`)));
  expect(screen.getAllByTestId(/muf-card-/)).toHaveLength(25);
  expect(toast.error).toHaveBeenCalled();
});
