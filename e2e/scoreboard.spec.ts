import { expect, test } from "./fixtures";
import { decide, endRun, latest, pay, REASONS } from "./api";

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
  // The app creates the evaluation and asks the agent to work it.
  await expect(async () => {
    const asked = await latest(request, "work_run");
    const run = (await (
      await request.get(`/api/runs/${String(asked.run_id)}`)
    ).json()) as Record<string, unknown>;
    expect(run).toMatchObject({
      kind: "evaluation",
      set_name: "held_out",
      tiny: true,
      n: 5,
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
      version: null,
      round_id: null,
    },
  });
  expect(created.ok()).toBe(true);
  const run = (await created.json()) as {
    run_id: number;
    claims: { claim_id: string; source_id: string }[];
  };
  const copy = (source: string) =>
    run.claims.find((entry) => entry.source_id === source)?.claim_id ?? "";
  const answers: [string, "approve" | "decline" | "refer", number][] = [
    ["CLM-1007", "approve", 50],
    ["CLM-1015", "decline", 0],
    ["CLM-1017", "refer", 0],
    ["CLM-1020", "approve", 300],
    ["CLM-1021", "approve", 825],
  ];
  for (const [source, decision, payout] of answers) {
    await decide(request, copy(source), decision, payout);
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
  await expect(row).toContainText("2.00");
  const asked = (await (
    await request.get("http://127.0.0.1:8005/asked")
  ).json()) as { handler: { reason: string }; agent: { rationale: string } }[];
  expect(asked).toHaveLength(5);
  expect(asked[0]?.agent.rationale).toBe(REASONS);
  expect(asked[0]?.handler.reason).toBeTruthy();

  await row
    .getByRole("link", { name: `Evaluation ${String(run.run_id)}` })
    .click();
  await expect(page.getByText("1 of 5 claims missed")).toBeVisible();
  const miss = page.getByRole("row").filter({ hasText: copy("CLM-1020") });
  await expect(miss).toContainText("Approved $240.00");
  await expect(miss).toContainText("Approved $300.00");
  await expect(miss).toContainText("Miss");
  await expect(miss).toContainText("B (2.00)YesNo");

  await page.getByRole("link", { name: copy("CLM-1021") }).click();
  await expect(page.getByText(/Nobody signs off a copy/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign off" })).toHaveCount(0);
});
