import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it } from "vitest";
import SiteFooter from "../../src/components/SiteFooter";
import { I18nProvider } from "../../src/i18n";

function renderFooter() {
  return render(
    <MemoryRouter>
      <I18nProvider>
        <SiteFooter />
      </I18nProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => localStorage.clear());

it("renders copyright, mailto, external site link, and /feedback link (en default)", () => {
  renderFooter();
  expect(screen.getByTestId("site-footer")).toBeInTheDocument();
  expect(screen.getByText("© 2026 Nguyen Duy")).toBeInTheDocument();
  const mail = screen.getByRole("link", { name: "nguyenduy2004.d@gmail.com" });
  expect(mail).toHaveAttribute("href", "mailto:nguyenduy2004.d@gmail.com");
  const site = screen.getByRole("link", { name: "ngduyd.id.vn" });
  expect(site).toHaveAttribute("href", "https://ngduyd.id.vn");
  expect(site).toHaveAttribute("target", "_blank");
  expect(site).toHaveAttribute("rel", expect.stringContaining("noopener"));
  expect(screen.getByRole("link", { name: "Feedback" })).toHaveAttribute("href", "/feedback");
});

it("renders VI copy ('Góp ý') when stored lang is vi", () => {
  localStorage.setItem("lang", "vi");
  renderFooter();
  expect(screen.getByRole("link", { name: "Góp ý" })).toHaveAttribute("href", "/feedback");
  expect(screen.getByText("© 2026 Nguyen Duy")).toBeInTheDocument();
});
