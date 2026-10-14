import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it } from "vitest";
import { I18nProvider } from "../../src/i18n";
import LangSwitch from "../../src/components/LangSwitch";

beforeEach(() => localStorage.clear());

it("clicking VI without provider writes localStorage('lang')", async () => {
  render(<LangSwitch />);
  await userEvent.click(screen.getByTestId("lang-switch-vi"));
  expect(localStorage.getItem("lang")).toBe("vi");
});

it("mount reads stored lang (vi default pre-render)", () => {
  localStorage.setItem("lang", "vi");
  render(<LangSwitch />);
  expect(screen.getByTestId("lang-switch-vi")).toHaveAttribute("aria-pressed", "true");
});

it("inside provider setLang flips consumers (context wiring)", async () => {
  render(
    <I18nProvider>
      <LangSwitch />
      <LangSwitch testid="mirror" />
    </I18nProvider>,
  );
  expect(screen.getByTestId("mirror-en")).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByTestId("lang-switch-vi"));
  expect(screen.getByTestId("mirror-vi")).toHaveAttribute("aria-pressed", "true");
  expect(localStorage.getItem("lang")).toBe("vi");
});
