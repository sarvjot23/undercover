import type { Page } from "@playwright/test";
import { test as base, expect } from "@playwright/test";

// The handlers' password at the stand-in for Supabase Auth.
export const PASSWORD = "e2e-password";
export const DANA = "dana.whitfield@undercover.example";
export const MARCUS = "marcus.oyelaran@undercover.example";

/** Sign in on the dashboard as a handler, through the stand-in for Supabase Auth. */
export async function signIn(page: Page, email: string) {
  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

/** Sign out, then in again as another handler. */
export async function switchTo(page: Page, email: string) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await signIn(page, email);
}

/** Every spec's page starts signed in as Dana Whitfield. */
export const test = base.extend({
  page: async ({ page }, use) => {
    await signIn(page, DANA);
    await use(page);
  },
});

export { expect };
