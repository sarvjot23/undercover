import { expect, MARCUS, switchTo, test } from "./fixtures";

test("Dana changes a setting after a confirmation, and Marcus can't", async ({
  page,
  request,
}) => {
  await page.goto("/#/settings");
  const agents = page.getByRole("spinbutton", { name: /Claim agents at once/ });
  await expect(agents).toHaveValue("25");
  await agents.fill("10");
  await page.getByRole("button", { name: "Save changes" }).click();
  const dialog = page.getByRole("dialog", { name: "Change the settings?" });
  await expect(dialog).toContainText("Claim agents at once: 25 to 10");
  await dialog.getByRole("button", { name: "Change the settings" }).click();
  await expect(dialog).toHaveCount(0);
  const changes = page.getByRole("region", { name: "Changes" });
  await expect(changes).toContainText("Dana Whitfield");
  await expect(changes).toContainText("Claim agents at once");

  const saved = (await (await request.get("/api/settings")).json()) as {
    settings: { agents_at_once: number };
  };
  expect(saved.settings.agents_at_once).toBe(10);

  await switchTo(page, MARCUS);
  await page.goto("/#/settings");
  await expect(
    page.getByText(
      "Only a handler who can sign off payouts over the limit can change the settings.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("spinbutton")).toHaveCount(0);
});

test("the theme switches and the browser remembers it", async ({ page }) => {
  await page.goto("/#/settings");
  await page.getByRole("radio", { name: "Dark" }).check();
  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-theme", "dark");
  const background = () =>
    page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(await background()).toBe("rgb(10, 10, 10)");
  await page.reload();
  await expect(root).toHaveAttribute("data-theme", "dark");
  await page.getByRole("radio", { name: "Light" }).check();
  expect(await background()).toBe("rgb(245, 243, 238)");
});
