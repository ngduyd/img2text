import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it } from "vitest";
import Features from "../../src/pages/Features";
import { I18nProvider } from "../../src/i18n";

function renderFeatures() {
  return render(
    <MemoryRouter>
      <I18nProvider>
        <Features />
      </I18nProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => localStorage.clear());

it("renders hero 'In the feature' + 'Coming soon' badge (en default)", () => {
  renderFeatures();
  expect(screen.getByTestId("features-page")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("In the feature");
  expect(screen.getByTestId("features-badge")).toHaveTextContent("Coming soon");
});

it("renders exactly 3 feature cards: workers, storage, members", () => {
  renderFeatures();
  expect(screen.getByTestId("feature-card-workers")).toHaveTextContent("Custom worker pools");
  expect(screen.getByTestId("feature-card-storage")).toHaveTextContent("Org-level storage");
  expect(screen.getByTestId("feature-card-members")).toHaveTextContent("Shared quotas & members");
});

it("switches to VI: title + card copy localized", () => {
  localStorage.setItem("lang", "vi");
  renderFeatures();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Tính năng sắp tới");
  expect(screen.getByTestId("features-badge")).toHaveTextContent("Sắp ra mắt");
  expect(screen.getByTestId("feature-card-workers")).toHaveTextContent("Pool worker tự cấu hình");
});
