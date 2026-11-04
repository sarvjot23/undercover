import { expect, test } from "./fixtures";
import { createDispatch, decide, endRun, pay, received, start } from "./api";

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
  await expect(async () => {
    expect(await received(request)).toContainEqual({
      path: "/dispatches",
      body: { n: 5 },
    });
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
          model: "m",
          reasoning: "low",
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
