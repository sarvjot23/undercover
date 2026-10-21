import { expect, test } from "@playwright/test";

test("the queue shows the 25 claims waiting", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "The claims queue" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(25);
  await expect(page.locator("tbody").getByText("Waiting")).toHaveCount(25);
  await expect(page.getByRole("link", { name: "CLM-1001" })).toBeVisible();
});

test("the instructions are shown read only", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Instructions" }).click();
  await expect(page.getByText(/You are the UnderCover Agent/)).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
});
