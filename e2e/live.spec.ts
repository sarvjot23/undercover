import { expect, test } from "@playwright/test";

test("the live view follows two claims through to their stamps", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);
  await page.goto("/#/live");
  await expect(
    page.getByText("Waiting for the agent to pick up a claim"),
  ).toBeVisible();

  const decide = async (claimId: string, decision: string) => {
    await request.post(`/api/claims/${claimId}/decision`, {
      data: {
        decision,
        payout: 0,
        reasons: "Recorded by the end-to-end test.",
        policy_section: "9. General exclusions",
      },
    });
  };

  await request.post("/api/claims/CLM-1020/start");
  const first = page.getByRole("article", { name: "Claim CLM-1020" });
  await expect(first).toBeVisible();
  await expect(first.getByRole("heading", { level: 1 })).toHaveText(
    /Prescription sunglasses stolen by a monkey/,
  );
  await decide("CLM-1020", "decline");
  await expect(page.getByRole("status")).toContainText("Declined");

  await request.post("/api/claims/CLM-1021/start");
  await expect(
    page.getByRole("article", { name: "Claim CLM-1021" }),
  ).toBeVisible();
  await decide("CLM-1021", "refer");
  await expect(page.getByRole("status")).toContainText("Referred");

  await expect(
    page.getByRole("heading", { name: "The queue is done" }),
  ).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Outcomes so far" }),
  ).toContainText("1 Declined");

  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("heading", { name: "The claims queue" }),
  ).toBeVisible();
});
