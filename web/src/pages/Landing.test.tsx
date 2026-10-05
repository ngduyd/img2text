import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import Landing from "./Landing";

// Reduced-motion path: render static (initial={false}), no transforms in jsdom.
vi.mock("motion/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("motion/react")>();
  return { ...actual, useReducedMotion: () => true };
});

// jsdom has no IntersectionObserver; whileInView feature mounts an observer.
class MockIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

function renderLanding() {
  return render(
    <MemoryRouter>
      <Landing />
    </MemoryRouter>,
  );
}

it("renders landing shell, H1, and CTA 'Bắt đầu' to /login", () => {
  renderLanding();
  expect(screen.getByTestId("landing")).toBeInTheDocument();
  expect(screen.getByTestId("landing-hero")).toBeInTheDocument();
  const h1 = screen.getByRole("heading", { level: 1 });
  expect(h1).toHaveTextContent("Biến ảnh và PDF thành văn bản sửa được");
  const cta = screen.getByTestId("landing-cta");
  expect(cta).toHaveTextContent("Bắt đầu");
  expect(cta).toHaveAttribute("href", "/login");
});

it("bento features section has exactly 5 cells", () => {
  renderLanding();
  expect(screen.getByTestId("landing-features")).toBeInTheDocument();
  expect(screen.getAllByTestId("feature-cell")).toHaveLength(5);
});

it("formats strip contains DOCX and the Colab free note", () => {
  renderLanding();
  const formats = screen.getByTestId("landing-formats");
  expect(formats).toHaveTextContent("DOCX");
  expect(formats).toHaveTextContent("Chạy miễn phí trên Google Colab");
});

it("#how shows verb-noun labels (no 'Bước')", () => {
  renderLanding();
  const how = screen.getByTestId("landing-how");
  expect(how).toHaveTextContent("Tải lên");
  expect(how).toHaveTextContent("Chỉnh sửa");
  expect(how).toHaveTextContent("Xuất file");
  expect(how.textContent).not.toMatch(/Bước\s*\d/i);
});

it("rendered text contains zero em-dashes", () => {
  const { container } = renderLanding();
  expect(container.textContent).not.toContain("—");
});
