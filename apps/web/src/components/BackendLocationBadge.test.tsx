import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { BackendLocationBadge } from "./BackendLocationBadge";

it.each([
  ["NVIDIA L4", "Modal L4"],
  ["Tesla T4", "Modal T4"],
  ["NVIDIA A10G", "Modal A10G"],
  ["NVIDIA L40S", "Modal L40S"],
  ["NVIDIA A100-SXM4-80GB", "Modal A100-SXM4-80GB"],
  [null, "Modal GPU"],
])("labels the actual GPU %s", (gpuName, label) => {
  render(<BackendLocationBadge location="modal" gpuName={gpuName} />);
  expect(screen.getByRole("status")).toHaveTextContent(label);
});

it("does not show a previous GPU when using the Mac", () => {
  render(<BackendLocationBadge location="mac" gpuName="NVIDIA A10G" />);
  expect(screen.getByRole("status")).toHaveTextContent("Mac");
  expect(screen.getByRole("status")).not.toHaveTextContent("A10G");
});

it("labels the actual AWS GPU separately from Modal", () => {
  render(<BackendLocationBadge location="aws" gpuName="NVIDIA L40S" />);
  expect(screen.getByRole("status")).toHaveTextContent("AWS L40S");
});

it("labels Windows separately from the Mac", () => {
  render(<BackendLocationBadge location="windows" />);
  expect(screen.getByRole("status")).toHaveTextContent("Windows");
});

it("places the Modal switch directly before the backend badge", () => {
  const change = vi.fn();
  const { rerender } = render(<BackendLocationBadge location="mac" modalControl={{ enabled: false, onChange: change }} />);
  const control = screen.getByRole("switch", { name: "GPU Modal" });
  expect(screen.getByRole("status").previousElementSibling).toContainElement(control);
  expect(control).toHaveAttribute("aria-checked", "false");
  fireEvent.click(control);
  expect(change).toHaveBeenCalledWith(true);
  rerender(<BackendLocationBadge location="modal" modalControl={{ enabled: true, busy: true, onChange: change }} />);
  expect(control).toHaveAttribute("aria-checked", "true");
  expect(control).toBeDisabled();
});
