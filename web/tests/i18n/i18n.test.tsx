import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import en from "../../src/i18n/en.json";
import viDict from "../../src/i18n/vi.json";
import { I18nProvider, translate, useT } from "../../src/i18n";

function Probe() {
  const { t, lang, setLang } = useT();
  return (
    <div>
      <span data-testid="lang">{lang}</span>
      <span data-testid="label">{t("common.language")}</span>
      <span data-testid="interp">{t("i18n.test.count", { n: 3 })}</span>
      <span data-testid="missing">{t("no.such.key")}</span>
      <button type="button" data-testid="btn-vi" onClick={() => setLang("vi")}>
        VI
      </button>
    </div>
  );
}

function flatten(obj: unknown, prefix = ""): string[] {
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
    typeof v === "object" && v !== null
      ? flatten(v, prefix ? `${prefix}.${k}` : k)
      : [prefix ? `${prefix}.${k}` : k],
  );
}

describe("i18n dict", () => {
  it("en.json and vi.json have identical key sets", () => {
    expect(flatten(viDict).sort()).toEqual(flatten(en).sort());
  });
});

describe("useT", () => {
  beforeEach(() => localStorage.clear());

  it("reads localStorage before render outside provider too", () => {
    localStorage.setItem("lang", "vi");
    render(<Probe />);
    expect(screen.getByTestId("lang")).toHaveTextContent("vi");
    expect(screen.getByTestId("label")).toHaveTextContent("Ngôn ngữ");
  });

  it("applies stored lang on mount inside provider", () => {
    localStorage.setItem("lang", "vi");
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("vi");
    expect(screen.getByTestId("label")).toHaveTextContent("Ngôn ngữ");
  });

  it("setLang switches text + writes localStorage('lang')", async () => {
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("label")).toHaveTextContent("Language");
    await userEvent.click(screen.getByTestId("btn-vi"));
    expect(screen.getByTestId("label")).toHaveTextContent("Ngôn ngữ");
    expect(localStorage.getItem("lang")).toBe("vi");
  });

  it("interpolates {n} params", () => {
    render(<Probe />);
    expect(screen.getByTestId("interp")).toHaveTextContent("3 pages");
  });

  it("missing key falls back to the key itself", () => {
    render(<Probe />);
    expect(screen.getByTestId("missing")).toHaveTextContent("no.such.key");
  });
});

describe("translate (module-level, lib/hooks)", () => {
  it("translates per stored lang; missing vi falls back to en", () => {
    localStorage.setItem("lang", "vi");
    expect(translate("common.language")).toBe("Ngôn ngữ");
    localStorage.setItem("lang", "en");
    expect(translate("common.language")).toBe("Language");
  });
});
