import { expect, it } from "vitest";
import { needsRenewal, RENEW_WITHIN_SECONDS } from "./auth";

it("renews a sign-in with less than 20 minutes left, and not one with more", () => {
  const now = 1_000_000;
  expect(RENEW_WITHIN_SECONDS).toBe(1200);
  expect(needsRenewal(now + 19 * 60, now)).toBe(true);
  expect(needsRenewal(now + 21 * 60, now)).toBe(false);
  expect(needsRenewal(undefined, now)).toBe(true);
});
