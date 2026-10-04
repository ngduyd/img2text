import { render, screen } from "@testing-library/react";
import MarkdownPreview from "./MarkdownPreview";

it("renders sanitized markdown in sandboxed iframe", () => {
  render(<MarkdownPreview markdown={"## Part 2\n\n| A | B |\n|---|---|\n| 1 | 2 |"} />);
  const iframe = screen.getByTestId("preview-markdown");
  expect(iframe).toHaveAttribute("sandbox", "");
  expect(iframe.getAttribute("srcdoc")).toContain("<h2");
  expect(iframe.getAttribute("srcdoc")).toContain("<table");
});

it("strips script and event handlers", () => {
  render(<MarkdownPreview markdown={"# Hi\n\n<img src=x onerror=alert(1)>\n\n<script>alert(2)</script>"} />);
  const srcdoc = screen.getByTestId("preview-markdown").getAttribute("srcdoc") ?? "";
  expect(srcdoc).not.toContain("onerror");
  expect(srcdoc).not.toContain("<script>alert(2)</script>");
});
