import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { StatusBadge } from "./StatusBadge";

afterEach(cleanup);

it("shows a claim sent back to the agent in the queue's words", () => {
  render(<StatusBadge status="sent_back" />);
  const badge = screen.getByText("Sent back");
  expect(badge.className).toContain("tone-antique");
});
