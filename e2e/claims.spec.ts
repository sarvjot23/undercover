import { expect, MARCUS, switchTo, test } from "./fixtures";
import { decide, pay, received } from "./api";

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
  await pay(request, "CLM-1013", 123);
  await page.goto("/#/claims/CLM-1013");
  await expect(page.locator(".claim-head .badge")).toHaveText("Decided");
  await expect(page.locator(".outcome")).toHaveText(/Approved\s*\$123\.00/);
  await expect(page.locator(".paid")).toContainText("Paid $123.00");
});

test("an approval over $800 waits for a sign-off, which pays it", async ({
  page,
  request,
}) => {
  await decide(request, "CLM-1014", "approve", 805);
  const refused = await request.post("/api/claims/CLM-1014/payment", {
    data: { amount: 805 },
  });
  expect(refused.status()).toBe(403);

  await page.goto("/#/claims/CLM-1014");
  await expect(page.locator(".claim-head .badge")).toHaveText(
    "Waiting for sign-off",
  );
  await expect(page.locator(".paid")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Sign off as Dana Whitfield" })
    .click();
  await expect(page.locator(".claim-head .badge")).toHaveText("Decided");
  await expect(page.locator(".paid")).toContainText("Paid $805.00 on");
  await expect(page.locator(".paid")).toContainText(
    "signed off by Dana Whitfield",
  );

  // The agent is only told to close its paused work: it pays nothing.
  await expect(async () => {
    expect(await received(request)).toContainEqual({
      operation: "resume_claim",
      claim_id: "CLM-1014",
    });
  }).toPass();
});

test("a decision sent back with a note waits for the agent", async ({
  page,
  request,
}) => {
  await decide(request, "CLM-1009", "approve", 950);
  await page.goto("/#/claims/CLM-1009");
  await page.getByRole("button", { name: "Send back" }).click();
  await page
    .getByLabel("What should the agent look at again?")
    .fill("The airline already refunded one night. Please take it off.");
  await page.getByRole("button", { name: "Send back to the agent" }).click();
  await expect(page.locator(".claim-head .badge")).toHaveText("Sent back");
  await expect(page.getByText(/Waiting for the next dispatch/)).toBeVisible();
  await expect(page.locator(".sent-back")).toContainText(
    "Dana Whitfield sent back approved $950.00",
  );
  await expect(page.locator(".note")).toHaveText(
    "The airline already refunded one night. Please take it off.",
  );
  await expect(page.locator(".step-send_back")).toContainText(
    "Sent back by Dana Whitfield",
  );
  await expect(page.getByText("No decision yet.")).toBeVisible();

  await page.goto("/");
  await expect(
    page.getByRole("row", { name: /CLM-1009/ }).locator(".badge"),
  ).toHaveText("Sent back");

  // The agent is asked to take the claim and decide again.
  await expect(async () => {
    expect(await received(request)).toContainEqual({
      operation: "resume_claim",
      claim_id: "CLM-1009",
    });
  }).toPass();
});

test("Marcus sees why he can't sign off a held payout", async ({
  page,
  request,
}) => {
  await decide(request, "CLM-1015", "approve", 900);
  await switchTo(page, MARCUS);
  await page.goto("/#/claims/CLM-1015");
  await expect(
    page.getByText(
      "Only a handler who can sign off payouts over the limit can sign this off or send it back.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Sign off as/ })).toHaveCount(
    0,
  );
});
