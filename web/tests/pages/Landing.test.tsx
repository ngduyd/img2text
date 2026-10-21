import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import Landing from "../../src/pages/Landing";

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

it("renders landing shell, H1, and CTA 'Get started' to /signin", () => {
  renderLanding();
  expect(screen.getByTestId("landing")).toBeInTheDocument();
  expect(screen.getByTestId("landing-hero")).toBeInTheDocument();
  const h1 = screen.getByRole("heading", { level: 1 });
  expect(h1).toHaveTextContent("Turn photos and PDFs into editable text");
  const cta = screen.getByTestId("landing-cta");
  expect(cta).toHaveTextContent("Get started");
  expect(cta).toHaveAttribute("href", "/signin");
});

// D6: roadmap gộp trang /features cũ (workers/storage/members) vào #roadmap.
it("roadmap section lists 3 coming-soon items", () => {
  renderLanding();
  const roadmap = screen.getByTestId("landing-roadmap");
  expect(roadmap).toHaveAttribute("id", "roadmap");
  expect(within(roadmap).getAllByTestId("roadmap-item")).toHaveLength(3);
  expect(roadmap).toHaveTextContent("Org-level storage");
});

it("formats strip contains DOCX and the Colab free note", () => {
  renderLanding();
  const formats = screen.getByTestId("landing-formats");
  expect(formats).toHaveTextContent("DOCX");
  expect(formats).toHaveTextContent("Runs free on Google Colab");
});

it("#how shows pipeline labels OCR/IR/Layout (no 'Bước')", () => {
  renderLanding();
  const how = screen.getByTestId("landing-how");
  expect(how).toHaveTextContent("OCR");
  expect(how).toHaveTextContent("IR");
  expect(how).toHaveTextContent("Layout");
  expect(how.textContent).not.toMatch(/Bước\s*\d/i);
});

it("reduced-motion path renders statically: no transform animation values", () => {
  const { container } = renderLanding();
  // useReducedMotion mocked true → initial={false}. framer-motion may still emit
  // "transform: none" (identity, no motion) — pin that: no real transform values.
  const styled = [...container.querySelectorAll("[style*='transform']")];
  for (const el of styled) {
    expect(el.getAttribute("style")).toMatch(/transform:\s*none/);
  }
});

// Bỏ 6 slot screenshot rỗng (ảnh chưa từng capture) → 1 mock tĩnh, không network.
it("hero shows a static mock instead of empty screenshot slots", () => {
  renderLanding();
  expect(screen.getByTestId("landing-mock")).toBeInTheDocument();
  expect(screen.queryByTestId("landing-gallery")).not.toBeInTheDocument();
  expect(screen.queryAllByTestId("gallery-shot")).toHaveLength(0);
  expect(screen.getByTestId("landing").querySelectorAll("img")).toHaveLength(0);
});

it("rendered text contains zero em-dashes", () => {
  const { container } = renderLanding();
  expect(container.textContent).not.toContain("—");
});
