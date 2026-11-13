import { expect, MARCUS, switchTo, test } from "./fixtures";
import { latest } from "./api";

test("a round started on the page, its proposal approved and the round carried on", async ({
  page,
  request,
}) => {
  await page.goto("/#/improvement");
  await page.getByRole("button", { name: "Start a round" }).click();
  const dialog = page.getByRole("dialog", { name: "Start a round?" });
  await dialog.getByRole("button", { name: "Start a round" }).click();

  // The app opens the round and asks the agent to work it; the stand-in for the
  // agent makes a proposal, which waits for a handler.
  let roundId = 0;
  await expect(async () => {
    roundId = (await latest(request, "work_round")).round_id;
    expect(roundId).toBeGreaterThan(0);
  }).toPass();
  const steps = page.getByRole("list", { name: "Where the round has got to" });
  await expect(steps.locator('[aria-current="step"]')).toHaveText(
    "A change waiting for approval",
  );
  const proposal = page.getByRole("region", {
    name: "A change to the claim agent, waiting for approval",
  });
  await expect(proposal.locator("ins.diff-add")).toContainText(
    "Refer a claim when a required document is missing.",
  );
  await expect(proposal.locator(".model-change del")).toHaveText("low");
  await expect(proposal.locator(".model-change ins")).toHaveText("medium");

  await switchTo(page, MARCUS);
  await page.goto("/#/improvement");
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expect(
    page.getByText(/can approve or reject the improver.s proposals/).first(),
  ).toBeVisible();

  await switchTo(page, "dana.whitfield@undercover.example");
  await page.goto("/#/improvement");
  await page.getByRole("button", { name: "Approve" }).click();
  await page
    .getByRole("dialog", { name: "Approve this change?" })
    .getByRole("button", { name: "Approve" })
    .click();

  // The app records the review and asks the agent to carry the round on, by the
  // review's id; the stand-in reads it back, then finishes the round.
  await expect(async () => {
    const carried = await latest(request, "carry_round_on");
    expect(carried.round_id).toBe(roundId);
    const review = await request.get(
      `/api/rounds/${String(roundId)}/reviews/${String(carried.proposal_id)}`,
    );
    expect(await review.json()).toEqual({ decision: "approve", message: "" });
  }).toPass();
  const rounds = page.getByRole("table", { name: "Rounds" });
  await expect(rounds).toContainText("Approved the change: Dana Whitfield");
});
