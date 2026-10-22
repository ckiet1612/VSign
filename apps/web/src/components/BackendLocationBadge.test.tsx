import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
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
