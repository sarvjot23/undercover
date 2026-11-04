import { expect, MARCUS, switchTo, test } from "./fixtures";
import { received } from "./api";

test("starting a round reaches the agent's service with the handler", async ({
  page,
  request,
}) => {
  await page.goto("/#/improvement");
  await page.getByRole("button", { name: "Start a round" }).click();
  const dialog = page.getByRole("dialog", { name: "Start a round?" });
  await dialog.getByRole("button", { name: "Start a round" }).click();
  await expect(async () => {
    expect(await received(request)).toContainEqual({
      path: "/rounds",
      body: { handler_id: "HND-01" },
    });
  }).toPass();
});

test("a proposal played out through the API is approved on the page", async ({
  page,
  request,
}) => {
  // The test plays the agent's service: it opens a round and records a proposal.
  const created = await request.post("/api/rounds/records", {
    data: { handler_id: "HND-01" },
  });
  const round = (await created.json()) as { round_id: number };
  const path = `/api/rounds/${String(round.round_id)}`;
  await request.post(`${path}/proposals/change`, {
    data: {
      instructions: "Refer a claim when a required document is missing.",
      model: "openai/gpt-6-luna",
      reasoning: "medium",
      reason: "Three misses had a document missing.",
    },
  });

  await page.goto("/#/improvement");
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
  await expect(async () => {
    expect(await received(request)).toContainEqual({
      path: `/rounds/${String(round.round_id)}/decision`,
      body: { decision: "approve", message: "", handler_id: "HND-01" },
    });
  }).toPass();

  // As the service would, record the decision; the page moves on.
  await request.post(`${path}/decisions`, {
    data: { decision: "approve", message: "", handler_id: "HND-01" },
  });
  await expect(steps.locator('[aria-current="step"]')).toHaveText(
    "The improver at work",
  );
  await request.post(`${path}/finish`);
  const rounds = page.getByRole("table", { name: "Rounds" });
  await expect(rounds).toContainText("Approved the change: Dana Whitfield");
});
