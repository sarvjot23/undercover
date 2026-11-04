import { expect, test } from "@playwright/test";
import { DANA, signIn } from "./fixtures";

test("every page waits for a handler to sign in, with no sign-up", async ({
  page,
}) => {
  await page.goto("/#/scoreboard");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await expect(page.getByText(/sign up/i)).toHaveCount(0);
});

test("a wrong password is refused", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Email").fill(DANA);
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "The email or password is wrong.",
  );
});

test("a handler signs in, sees who is signed in, and signs out", async ({
  page,
}) => {
  await signIn(page, DANA);
  await expect(page.getByText("Dana Whitfield")).toBeVisible();
  await expect(page.getByText("Senior Claims Handler")).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("the backend refuses an action without a sign-in", async ({ request }) => {
  const refused = await request.post("/api/dispatches", { data: { n: 3 } });
  expect(refused.status()).toBe(401);
});
