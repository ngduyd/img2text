import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import Legal from "../../src/pages/Legal";
import { I18nProvider } from "../../src/i18n";

function renderLegal() {
  return render(
    <MemoryRouter initialEntries={["/legal"]}>
      <I18nProvider>
        <Legal />
      </I18nProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => localStorage.clear());

describe("Legal (spec 2026-11-04 A1/A5)", () => {
  it("renders title + 4 nội dung thật (en default)", () => {
    renderLegal();
    expect(screen.getByRole("heading", { level: 1, name: "Terms of Service" })).toBeInTheDocument();
    for (const key of ["service", "data", "responsibilities", "rights"]) {
      expect(screen.getByTestId(`legal-${key}`)).toBeInTheDocument();
    }
    // nội dung thật: không placeholder — có Kaggle, 7 ngày, LLM, xoá job
    const body = screen.getByTestId("card-legal").textContent ?? "";
    expect(body).toMatch(/kaggle/i);
    expect(body).toMatch(/7 days/i);
    expect(body).toMatch(/llm/i);
    expect(body).toMatch(/delete a job/i);
  });

  it("renders VI copy", () => {
    localStorage.setItem("lang", "vi");
    renderLegal();
    expect(screen.getByRole("heading", { level: 1, name: "Điều khoản sử dụng" })).toBeInTheDocument();
  });
});
