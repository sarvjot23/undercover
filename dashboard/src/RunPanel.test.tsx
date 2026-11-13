import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { RunPanel } from "./RunPanel";
import { runRecord } from "./testing";

afterEach(cleanup);

it("says why a dispatch stopped", () => {
  render(
    <RunPanel
      run={runRecord({
        status: "stopped",
        stop_reason: "The agent stopped answering",
      })}
    />,
  );
  expect(
    screen.getByText(/Stopped partway: The agent stopped answering/),
  ).toBeDefined();
});
