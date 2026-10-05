import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import Card from "./Card";

it("renders title in header, children, testid", () => {
  render(
    <Card title="Thông tin" testid="card-x">
      <p>Nội dung</p>
    </Card>,
  );
  const card = screen.getByTestId("card-x");
  expect(card).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Thông tin" })).toBeInTheDocument();
  expect(card).toHaveTextContent("Nội dung");
});

it("renders actions slot in header", () => {
  render(
    <Card title="Bảng" testid="card-x" actions={<button type="button">Hành động</button>}>
      body
    </Card>,
  );
  expect(screen.getByRole("button", { name: "Hành động" })).toBeInTheDocument();
});

it("works without title", () => {
  render(
    <Card testid="card-x">
      <p>Không tiêu đề</p>
    </Card>,
  );
  expect(screen.getByTestId("card-x")).toHaveTextContent("Không tiêu đề");
});
