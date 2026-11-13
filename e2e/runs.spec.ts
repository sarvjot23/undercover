import { expect, test } from "./fixtures";
import {
  createDispatch,
  decide,
  endRun,
  pay,
  latest,
  record,
  start,
} from "./api";

test("starting a dispatch on the dashboard reaches the agent's service with N", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const agents = page.getByRole("spinbutton", {
    name: "Claim agents at once",
  });
  await expect(agents).toHaveValue("3");
  await agents.fill("5");
  await page.getByRole("button", { name: "Start a dispatch" }).click();
  await expect(page).toHaveURL(/#\/live$/);
  // The app creates the dispatch and asks the agent to work it.
  await expect(async () => {
    const asked = await latest(request, "work_run");
    const run = (await (
      await request.get(`/api/runs/${String(asked.run_id)}`)
    ).json()) as { kind: string; n: number };
    expect(run).toMatchObject({ kind: "dispatch", n: 5 });
  }).toPass();
});

test("the run panel plays out a dispatch to the summary from the records", async ({
  page,
  request,
}) => {
  const runId = await createDispatch(request, 3);
  await page.goto("/");
  const panel = page.getByRole("region", { name: "The latest dispatch" });
  await expect(panel).toContainText("Running · 3 claim agents at once");
  const claims = panel.getByRole("list", { name: "The dispatch's claims" });
  await expect(claims.getByRole("listitem").first()).toBeVisible();

  await decide(request, "CLM-1003", "refer", 0);
  await decide(request, "CLM-1004", "approve", 74);
  await pay(request, "CLM-1004", 74);
  await decide(request, "CLM-1008", "approve", 2240);
  await expect(
    claims.getByRole("listitem").filter({ hasText: "CLM-1008" }),
  ).toContainText("Waiting for sign-off");

  await endRun(request, runId);
  await expect(panel).toContainText("Finished");
  await expect(panel).toContainText("2 approved, 0 declined and 1 referred.");
  await expect(panel).toContainText(
    "Waiting for a sign-off: CLM-1008 $2,240.00",
  );
  await expect(panel).toContainText("Model cost$0.00");
});

test("a dispatch can't start while one is running", async ({
  page,
  request,
}) => {
  const runId = await createDispatch(request);
  await page.goto("/");
  await expect(
    page.getByText("A dispatch or evaluation is already running"),
  ).toBeVisible();
  const button = page.getByRole("button", { name: "Start a dispatch" });
  await expect(button).toBeDisabled();
  expect(
    (
      await request.post("/api/runs", {
        data: {
          kind: "dispatch",
          n: 3,
          set_name: null,
          tiny: false,
          version: null,
          round_id: null,
        },
      })
    ).status(),
  ).toBe(409);

  await endRun(request, runId, "stop");
  await expect(button).toBeEnabled();
  await expect(
    page.getByText("A dispatch or evaluation is already running"),
  ).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "The latest dispatch" }),
  ).toContainText("Stopped partway");
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
  await page.getByRole("table").getByRole("link", { name: "CLM-1005" }).click();
  await expect(page.getByText("2 failed attempts")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run the agent" })).toHaveCount(
    0,
  );
});

test("a claim page shows the context the agent used and the calculation", async ({
  page,
  request,
}) => {
  const manual = {
    file: "claims_manual.md",
    system: "Claims operations",
    owner: "Head of claims operations",
    reviewed: "2026-09-01",
  };
  const glossary = {
    file: "glossary.yaml",
    system: "The policy wording, version 2026.1",
    owner: "Legal",
    reviewed: "2026-09-01",
  };
  expect((await start(request, "CLM-1006")).ok()).toBe(true);
  const lookups = [
    ["The term “Unattended”", [glossary]],
    ["Claims manual · 7. Interpretation notes", [manual]],
    ["Claims manual · 7. Interpretation notes", [manual]],
  ] as const;
  for (const [index, [lookedUp, files]] of lookups.entries()) {
    const step = await request.post("/api/claims/CLM-1006/steps", {
      data: {
        kind: "lookup",
        text: lookedUp,
        key: `e2e-lookup-${String(index)}`,
        detail: { looked_up: lookedUp, files },
      },
    });
    expect(step.ok()).toBe(true);
  }
  await record(request, "CLM-1006", "approve", 325);
  await page.goto("/#/claims/CLM-1006");

  await expect(page.getByText("Looked up")).toHaveCount(3);
  const used = page.getByRole("region", { name: "Context used" });
  await expect(used.getByRole("region")).toHaveCount(2);
  await expect(
    used
      .getByRole("region", { name: "claims_manual.md" })
      .getByRole("listitem"),
  ).toHaveText(["Claims manual · 7. Interpretation notes"]);
  await expect(
    used.getByRole("region", { name: "glossary.yaml" }),
  ).toContainText("The policy wording, version 2026.1, owned by Legal");

  const calculation = page.getByRole("table", { name: "Calculation" });
  await expect(calculation.getByRole("row").last()).toHaveText("Payout$325.00");
  await expect(page.getByText("UnderCover Agent, version 1")).toBeVisible();
});
