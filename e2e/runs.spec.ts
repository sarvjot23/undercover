import { expect, test } from "@playwright/test";
import { finishRun, openRun, pay, start, work, writeTodos } from "./api";

test("the run panel ticks off the to-do list, then shows the summary", async ({
  page,
  request,
}) => {
  const runId = await openRun(request, 2);
  await page.goto("/");
  await expect(page.getByText("The agent is planning the run.")).toBeVisible();

  await writeTodos(request, runId, [
    { claim_id: "CLM-1003", note: "Emergency medical", status: "in_progress" },
    { claim_id: "CLM-1004", note: "Baggage delay", status: "to_do" },
  ]);
  const panel = page.getByRole("region", { name: "The agent’s to-do list" });
  const items = panel.getByRole("listitem");
  await expect(items).toHaveCount(2);
  await expect(items.nth(0)).toContainText("In progress");
  await expect(items.nth(1)).toContainText("To do");

  await work(request, runId, "CLM-1003", "refer", 0);
  await writeTodos(request, runId, [
    { claim_id: "CLM-1003", note: "Emergency medical", status: "done" },
    { claim_id: "CLM-1004", note: "Baggage delay", status: "in_progress" },
  ]);
  await expect(items.nth(0)).toContainText("Done");
  await expect(panel).toContainText("1 of 2 claims taken");

  await work(request, runId, "CLM-1004", "approve", 74);
  await pay(request, "CLM-1004", 74);
  await writeTodos(request, runId, [
    { claim_id: "CLM-1003", note: "Emergency medical", status: "done" },
    { claim_id: "CLM-1004", note: "Baggage delay", status: "done" },
  ]);
  await finishRun(request, runId, "One referred and one approved for $74.00.");
  await expect(
    panel.getByText("One referred and one approved for $74.00."),
  ).toBeVisible();
  await expect(panel).toContainText("The last run is finished");
});

test("a claim that fails twice is left for a handler", async ({
  page,
  request,
}) => {
  for (let attempt = 0; attempt < 2; attempt++) {
    await start(request, "CLM-1005");
    await request.post("/api/claims/CLM-1005/fail", {
      data: { reason: "The agent's run failed: timed out" },
    });
  }
  await page.goto("/");
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "CLM-1005" })
      .getByText("Left for a handler"),
  ).toBeVisible();
  await page.getByRole("link", { name: "CLM-1005" }).click();
  await expect(page.getByText("2 failed attempts")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run the agent" })).toHaveCount(
    0,
  );
});

test("a claim page lists the sections the agent read", async ({
  page,
  request,
}) => {
  for (const text of [
    "Policy wording · 6. Passport and Travel Documents",
    "Claims manual · 7. Interpretation notes",
  ]) {
    await request.post("/api/claims/CLM-1006/steps", {
      data: { kind: "read", text, key: text },
    });
  }
  await page.goto("/#/claims/CLM-1006");
  const reads = page.getByRole("region", { name: "What the agent read" });
  await expect(reads.getByRole("listitem")).toHaveText([
    "Policy wording · 6. Passport and Travel Documents",
    "Claims manual · 7. Interpretation notes",
  ]);
});

test("the live view follows a capped run to its summary", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);
  const runId = await openRun(request, 2);
  await page.goto("/#/live");

  await request.post(`/api/runs/${String(runId)}/claims/CLM-1007`);
  await start(request, "CLM-1007");
  await expect(
    page.getByRole("article", { name: "Claim CLM-1007" }),
  ).toBeVisible();
  await expect(page.getByText("Claim 1 of 2")).toBeVisible();
  await request.post("/api/claims/CLM-1007/decision", {
    data: {
      decision: "approve",
      payout: 50,
      reasons: "Recorded by the end-to-end test.",
      policy_section: "5. Baggage and Personal Effects",
    },
  });
  await pay(request, "CLM-1007", 50);
  await expect(page.getByRole("status")).toContainText("Approved");

  await request.post(`/api/runs/${String(runId)}/claims/CLM-1009`);
  for (let attempt = 0; attempt < 2; attempt++) {
    await start(request, "CLM-1009");
    await request.post("/api/claims/CLM-1009/fail", {
      data: { reason: "The agent's run failed: timed out" },
    });
  }
  await finishRun(request, runId, "One approved, one left for a handler.");
  await expect(
    page.getByRole("heading", { name: "The queue is done" }),
  ).toBeVisible({ timeout: 20_000 });
  await expect(
    page.getByText("One approved, one left for a handler."),
  ).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Outcomes so far" }),
  ).toContainText("1 Left for a handler");
});

test("the queue can't be run while a run is in progress", async ({
  page,
  request,
}) => {
  const runId = await openRun(request, 1);
  await page.goto("/");
  await expect(page.getByText("A run is already in progress")).toBeVisible();
  const button = page.getByRole("button", { name: "Run the queue" });
  await expect(button).toBeDisabled();
  expect((await request.post("/api/runs", { data: { cap: 1 } })).status()).toBe(
    409,
  );

  await request.post(`/api/runs/${String(runId)}/fail`, {
    data: { reason: "Ended by the end-to-end test." },
  });
  await expect(button).toBeEnabled();
  await expect(page.getByText("A run is already in progress")).toHaveCount(0);
});
