import { expect, test } from "@playwright/test";
import { endRun, pay, received } from "./api";

test("starting an evaluation on the Scoreboard page reaches the agent's service", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Scoreboard" }).click();
  await page
    .getByRole("combobox", { name: "Labelled set" })
    .selectOption({ label: "Held-out set" });
  await page
    .getByRole("combobox", { name: "Claims" })
    .selectOption({ label: "Five tiny claims" });
  await page
    .getByRole("spinbutton", { name: "Claim agents at once" })
    .fill("5");
  await page.getByRole("button", { name: "Start an evaluation" }).click();
  await expect(async () => {
    expect(await received(request)).toContainEqual({
      path: "/evaluations",
      body: { set_name: "held_out", tiny: true, n: 5 },
    });
  }).toPass();
});

test("an evaluation played out through the API shows on the scoreboard with its measures", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const tiles = page.locator(".tiles");
  await expect(tiles).toContainText("Waiting");
  const before = await tiles.textContent();

  const created = await request.post("/api/runs", {
    data: {
      kind: "evaluation",
      n: 5,
      set_name: "evaluation",
      tiny: true,
      model: "openai/gpt-6-luna",
      reasoning: "low",
    },
  });
  expect(created.ok()).toBe(true);
  const run = (await created.json()) as {
    run_id: number;
    claims: { claim_id: string; source_id: string }[];
  };
  const copy = (source: string) =>
    run.claims.find((entry) => entry.source_id === source)?.claim_id ?? "";
  const answers: [string, string, number][] = [
    ["CLM-1007", "approve", 50],
    ["CLM-1015", "decline", 0],
    ["CLM-1017", "refer", 0],
    ["CLM-1020", "approve", 300],
    ["CLM-1021", "approve", 825],
  ];
  for (const [source, decision, payout] of answers) {
    const claimId = copy(source);
    await request.post(`/api/claims/${claimId}/start`, {
      data: { thread_id: `${claimId}-e2e` },
    });
    await request.post(`/api/claims/${claimId}/decision`, {
      data: {
        decision,
        payout,
        reasons: "Recorded by the end-to-end test.",
        policy_section: "3. Trip Delay",
      },
    });
  }
  await pay(request, copy("CLM-1007"), 50);
  await pay(request, copy("CLM-1020"), 300);
  await endRun(request, run.run_id);

  await page.reload();
  await expect(tiles).toHaveText(before ?? "");

  await page.getByRole("link", { name: "Scoreboard" }).click();
  const row = page
    .getByRole("row")
    .filter({ hasText: `Evaluation ${String(run.run_id)}` });
  await expect(row).toContainText("Evaluation set");
  await expect(row).toContainText("Five tiny claims");
  await expect(row).toContainText("Finished");
  await expect(row).toContainText("100%");
  await expect(row).toContainText("80%");
  await expect(row).toContainText("$60.00");

  await row
    .getByRole("link", { name: `Evaluation ${String(run.run_id)}` })
    .click();
  await expect(page.getByText("1 of 5 claims missed")).toBeVisible();
  const miss = page.getByRole("row").filter({ hasText: copy("CLM-1020") });
  await expect(miss).toContainText("Approved $240.00");
  await expect(miss).toContainText("Approved $300.00");
  await expect(miss).toContainText("Miss");

  await page.getByRole("link", { name: copy("CLM-1021") }).click();
  await expect(page.getByText(/Nobody signs off a copy/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign off" })).toHaveCount(0);
});
