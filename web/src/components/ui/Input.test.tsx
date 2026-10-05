import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import Input from "./Input";

it("renders visible label associated with input (getByLabelText)", () => {
  render(<Input label="Email" testid="input-email" />);
  expect(screen.getByLabelText("Email")).toHaveAttribute("data-testid", "input-email");
});

it("spreads input props (type, value, onChange)", async () => {
  const onChange = vi.fn();
  render(
    <Input label="Mật khẩu" testid="input-password" type="password" value="" onChange={onChange} />,
  );
  const input = screen.getByLabelText("Mật khẩu");
  expect(input).toHaveAttribute("type", "password");
  await userEvent.type(input, "a");
  expect(onChange).toHaveBeenCalled();
});

it("error state: message shown, aria-invalid set, aria-describedby wired", () => {
  render(<Input label="Email" testid="input-email" error="Trường này bắt buộc." />);
  expect(screen.getByTestId("input-email-error")).toHaveTextContent("Trường này bắt buộc.");
  const input = screen.getByLabelText("Email");
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(input).toHaveAttribute("aria-describedby", "input-email-error");
});
