import { render, screen } from "@testing-library/react";
import App from "./App";

it("renders app shell with brand and nav links", () => {
  render(<App />);
  expect(screen.getByTestId("nav-brand")).toHaveTextContent("img2text");
  expect(screen.getByTestId("nav-link-jobs")).toBeInTheDocument();
  expect(screen.getByTestId("nav-link-admin")).toBeInTheDocument();
});
