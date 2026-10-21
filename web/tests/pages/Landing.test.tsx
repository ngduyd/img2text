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
it("hero + preview use real screenshots (3 ảnh, có alt, lazy)", () => {
  renderLanding();
  // R51: testid landing-mock giữ, giờ là <img> ảnh thật trong public/shots.
  const hero = screen.getByTestId("landing-mock");
  expect(hero.tagName).toBe("IMG");
  expect(hero).toHaveAttribute("src", "/shots/editor.jpg");
  expect(screen.getByTestId("landing-shot-jobs")).toHaveAttribute("src", "/shots/jobs.jpg");
  expect(screen.getByTestId("landing-shot-text")).toHaveAttribute("src", "/shots/text.jpg");
  const imgs = screen.getByTestId("landing").querySelectorAll("img");
  expect(imgs).toHaveLength(3);
  for (const img of imgs) {
    expect(img).toHaveAttribute("alt");
    expect(img.getAttribute("alt")).not.toBe("");
    expect(img).toHaveAttribute("loading", "lazy");
  }
});

it("rendered text contains zero em-dashes", () => {
  const { container } = renderLanding();
  expect(container.textContent).not.toContain("—");
});
