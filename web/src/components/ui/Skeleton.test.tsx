import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import Skeleton from "./Skeleton";

it("renders default testid skeleton, aria-hidden, shimmer class", () => {
  render(<Skeleton />);
  const el = screen.getByTestId("skeleton");
  expect(el).toHaveAttribute("aria-hidden", "true");
  expect(el.className).toContain("skeleton");
});

it("className override replaces default size (Task 2 sizing)", () => {
  render(<Skeleton testid="sk-1" className="h-8 w-40" />);
  const el = screen.getByTestId("sk-1");
  expect(el.className).toContain("h-8 w-40");
  expect(el.className).not.toContain("w-full");
});
