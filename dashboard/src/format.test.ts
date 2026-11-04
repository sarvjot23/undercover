import { expect, it } from "vitest";
import { cost, date, duration, label, money } from "./format";

it("formats money in US dollars", () => {
  expect(money(1250)).toBe("$1,250.00");
  expect(money(0)).toBe("$0.00");
});

it("formats dates", () => {
  expect(date("2026-06-24")).toBe("Jun 24, 2026");
  expect(date("2026-10-21T12:13:29+00:00")).toBe("Oct 21, 2026");
});

it("turns codes into labels", () => {
  expect(label("trip_delay")).toBe("Trip delay");
});

it("formats a model cost to a hundredth of a cent", () => {
  expect(cost(0.0123)).toBe("$0.0123");
  expect(cost(0.5)).toBe("$0.50");
});

it("formats a length of time", () => {
  expect(duration(42.4)).toBe("42s");
  expect(duration(185)).toBe("3m 05s");
});
