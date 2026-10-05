import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import Button from "./Button";

it("renders testid, children, default type button", () => {
  render(<Button testid="btn-x">Nhấn</Button>);
  const btn = screen.getByTestId("btn-x");
  expect(btn).toHaveTextContent("Nhấn");
  expect(btn).toHaveAttribute("type", "button");
});

it.each(["primary", "secondary", "ghost", "danger"] as const)(
  "variant %s exposed for styling/tests",
  (variant) => {
    render(<Button testid="btn-x" variant={variant}>X</Button>);
    expect(screen.getByTestId("btn-x")).toHaveAttribute("data-variant", variant);
  },
);

it.each(["sm", "md"] as const)("size %s exposed", (size) => {
  render(<Button testid="btn-x" size={size}>X</Button>);
  expect(screen.getByTestId("btn-x")).toHaveAttribute("data-size", size);
});

it("loading sets aria-busy and disables; disabled disables", () => {
  const { rerender } = render(<Button testid="btn-x" loading>Đang xử lý</Button>);
  expect(screen.getByTestId("btn-x")).toHaveAttribute("aria-busy", "true");
  expect(screen.getByTestId("btn-x")).toBeDisabled();
  rerender(<Button testid="btn-x" disabled>X</Button>);
  expect(screen.getByTestId("btn-x")).toBeDisabled();
});

it("onClick fires and passes through handler args", async () => {
  const onClick = vi.fn();
  render(
    <Button testid="btn-x" type="submit" onClick={onClick}>
      Gửi
    </Button>,
  );
  await userEvent.click(screen.getByTestId("btn-x"));
  expect(onClick).toHaveBeenCalledTimes(1);
  expect(screen.getByTestId("btn-x")).toHaveAttribute("type", "submit");
});
