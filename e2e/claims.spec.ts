import { expect, test } from "@playwright/test";
import { decide } from "./api";

test("a claim in full", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "CLM-1001" }).click();
  await expect(
    page.getByRole("heading", { name: /Flight home canceled/ }),
  ).toBeVisible();
  await expect(page.getByText(/My flight home from Rome/)).toBeVisible();
  await expect(page.locator(".items tbody tr")).toHaveCount(3);
  await expect(page.getByText("$420.00")).toBeVisible();
  await expect(page.locator("details.document")).toHaveCount(4);
  await expect(page.getByText(/CLM-0412/)).toBeVisible();
  await expect(page.getByText("No decision yet.")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run the agent" }),
  ).toBeVisible();
});

test("an approval under $800 is decided and paid", async ({
  page,
  request,
}) => {
  await decide(request, "CLM-1013", "approve", 123);
  const paid = await request.post("/api/claims/CLM-1013/payment", {
    data: { amount: 123 },
  });
  expect(paid.ok()).toBe(true);
  await page.goto("/#/claims/CLM-1013");
  await expect(page.locator(".claim-head .badge")).toHaveText("Decided");
  await expect(page.locator(".outcome")).toHaveText(/Approved\s*\$123\.00/);
  await expect(page.locator(".paid")).toContainText("Paid $123.00");
});

test("an approval over $800 waits for sign-off before it is paid", async ({
  page,
  request,
}) => {
  await decide(request, "CLM-1014", "approve", 805);
  const refused = await request.post("/api/claims/CLM-1014/payment", {
    data: { amount: 805 },
  });
  expect(refused.status()).toBe(409);

  await page.goto("/#/claims/CLM-1014");
  await expect(page.locator(".claim-head .badge")).toHaveText(
    "Waiting for sign-off",
  );
  await expect(page.locator(".paid")).toHaveCount(0);
  await page.getByRole("combobox").selectOption({ label: "Dana Whitfield" });
  await page.getByRole("button", { name: "Sign off" }).click();
  await expect(page.locator(".claim-head .badge")).toHaveText("Decided");
  await expect(page.locator(".paid")).toContainText("Paid $805.00 on");
  await expect(page.locator(".paid")).toContainText(
    "signed off by Dana Whitfield",
  );
});
