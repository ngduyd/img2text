import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import Badge from "./Badge";

it.each(["neutral", "success", "warning", "error", "info"] as const)(
  "tone %s exposed with text and testid",
  (tone) => {
    render(
      <Badge tone={tone} testid="badge-x">
        Nhãn
      </Badge>,
    );
    const el = screen.getByTestId("badge-x");
    expect(el).toHaveAttribute("data-tone", tone);
    expect(el).toHaveTextContent("Nhãn");
  },
);

it("defaults to neutral tone", () => {
  render(<Badge testid="badge-x">Mặc định</Badge>);
  expect(screen.getByTestId("badge-x")).toHaveAttribute("data-tone", "neutral");
});
