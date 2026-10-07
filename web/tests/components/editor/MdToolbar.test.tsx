import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import MdToolbar from "../../../src/components/editor/MdToolbar";

const OPS = [
  "undo",
  "redo",
  "h1",
  "h2",
  "h3",
  "bold",
  "italic",
  "strike",
  "list",
  "quote",
  "code",
  "link",
  "table",
] as const;

afterEach(() => {
  vi.restoreAllMocks();
});

it("renders every md-tb-* button with title + aria-label inside a toolbar role", () => {
  render(<MdToolbar onFormat={vi.fn()} />);
  expect(screen.getByRole("toolbar", { name: "Công cụ Markdown" })).toBeInTheDocument();
  for (const op of OPS) {
    const btn = screen.getByTestId(`md-tb-${op}`);
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute("title");
    expect(btn).toHaveAttribute("aria-label");
    expect(btn.tagName).toBe("BUTTON");
  }
});

it("clicking a plain action button emits its op (no arg)", () => {
  const onFormat = vi.fn();
  render(<MdToolbar onFormat={onFormat} />);
  for (const op of OPS) {
    if (op === "link") continue;
    onFormat.mockClear();
    fireEvent.click(screen.getByTestId(`md-tb-${op}`));
    expect(onFormat).toHaveBeenCalledTimes(1);
    expect(onFormat).toHaveBeenCalledWith(op);
  }
});

it("link prompts for URL and emits (link, url); cancelling emits nothing", () => {
  const onFormat = vi.fn();
  const prompt = vi.spyOn(window, "prompt");
  render(<MdToolbar onFormat={onFormat} />);
  prompt.mockReturnValue("https://a.vn");
  fireEvent.click(screen.getByTestId("md-tb-link"));
  expect(onFormat).toHaveBeenCalledWith("link", "https://a.vn");
  onFormat.mockClear();
  prompt.mockReturnValue(null);
  fireEvent.click(screen.getByTestId("md-tb-link"));
  expect(onFormat).not.toHaveBeenCalled();
});
