import { expect, test } from "./fixtures";
import { createDispatch, endRun, pay, start } from "./api";

test("the live view shows a dispatch as a board, stamps each claim and ends on the summary", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);
  const runId = await createDispatch(request, 2);
  await page.goto("/#/live");
  const board = page.getByRole("list", { name: `Dispatch ${String(runId)}` });
  await expect(board).toBeVisible();

  const decide = async (claimId: string, decision: string, payout: number) => {
    await request.post(`/api/claims/${claimId}/decision`, {
      data: {
        decision,
        payout,
        reasons: "Recorded by the end-to-end test.",
        policy_section: "9. General exclusions",
      },
    });
  };

  await start(request, "CLM-1020");
  await start(request, "CLM-1021");
  await request.post("/api/claims/CLM-1020/steps", {
    data: { kind: "tool_call", text: "get_claim CLM-1020", key: "e2e-live-1" },
  });
  const first = page.getByRole("article", { name: "Claim CLM-1020" });
  const second = page.getByRole("article", { name: "Claim CLM-1021" });
  await expect(first).toContainText("get_claim CLM-1020");
  await expect(second).toContainText("Starting");
  await expect(page.getByText(/· 2 at work/)).toBeVisible();

  await decide("CLM-1020", "decline", 0);
  await expect(first.getByRole("status")).toHaveText("Declined");
  await decide("CLM-1021", "approve", 50);
  await expect(second.getByRole("status")).toHaveCount(0);
  await pay(request, "CLM-1021", 50);
  await expect(second.getByRole("status")).toContainText("Approved");

  await endRun(request, runId);
  await expect(
    page.getByRole("heading", { name: "The dispatch is done" }),
  ).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Outcomes so far" }),
  ).toContainText("1 Declined");

  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("heading", { name: "The claims queue" }),
  ).toBeVisible();
});
