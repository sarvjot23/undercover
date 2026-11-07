import { expect, test } from "./fixtures";

test("the queue shows the 26 claims", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "The claims queue" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(26);
  await expect(
    page.getByRole("row").filter({ hasText: "CLM-1001" }).getByText("Waiting"),
  ).toBeVisible();
  await expect(
    page.getByRole("table").getByRole("link", { name: "CLM-1001" }),
  ).toBeVisible();
});

test("the configuration shows version 1 read only", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Configuration" }).click();
  await expect(
    page.getByRole("heading", { name: "Version 1, the current version" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("table", { name: "Versions" })
      .getByRole("row")
      .filter({ hasText: "The first version" }),
  ).toContainText("Seeded");
  await expect(page.getByLabel("The instructions in version 1")).toContainText(
    "You are the UnderCover Agent.",
  );
  await expect(page.getByRole("textbox")).toHaveCount(0);
});

test("the old Instructions address opens the configuration", async ({
  page,
}) => {
  await page.goto("/#/instructions");
  await expect(
    page.getByRole("heading", { name: "Configuration", exact: true }),
  ).toBeVisible();
});
