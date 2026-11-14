import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

function sidebar(page: Page) {
  return page.getByRole("complementary", { name: "Copilot" });
}

async function ask(page: Page, message: string) {
  const box = sidebar(page).getByRole("textbox", { name: "Ask the Copilot" });
  await box.fill(message);
  await box.press("Enter");
}

test("a question shows each step as it comes, then the formatted answer", async ({
  page,
}) => {
  const copilot = sidebar(page);
  await expect(copilot.getByText("Hello, Dana.")).toBeVisible();
  await ask(page, "What needs me today?");
  await expect(copilot.getByText("What needs me today?")).toBeVisible();
  await expect(copilot.getByRole("status")).toBeVisible();
  const steps = copilot.getByRole("list", { name: "Steps" });
  await expect(
    steps.getByRole("button", { name: /get_claim CLM-1003/ }),
  ).toBeVisible();
  await expect(
    steps.locator(".copilot-card.kind-action.state-done"),
  ).toBeVisible();
  const refused = steps.locator(".copilot-card.state-refused");
  await expect(refused).toContainText("Refused (409): Dispatch 1 is running");
  const table = copilot.getByRole("table");
  await expect(table).toContainText("$3,750.00");
  await expect(copilot.getByText("4 model calls · $0.0042")).toBeVisible();
  await steps.getByRole("button", { name: /get_claim CLM-1003/ }).click();
  await expect(copilot.getByText("Came back")).toBeVisible();
  await table.getByRole("link", { name: "CLM-1003" }).click();
  await expect(page).toHaveURL(/#\/claims\/CLM-1003$/);
});

test("the confirmation card waits, survives a reload, and carries the turn on", async ({
  page,
}) => {
  const copilot = sidebar(page);
  await ask(page, "Sign off on another one");
  const card = copilot.getByRole("region", { name: "Confirm the sign-off" });
  await expect(card).toContainText("Aiko Tanaka");
  await expect(card).toContainText("$3,750.00");
  await expect(
    copilot.getByRole("textbox", { name: "Ask the Copilot" }),
  ).toHaveAttribute("placeholder", "Answer the confirmation first");

  await page.reload();
  await copilot.getByRole("button", { name: "Earlier" }).click();
  await copilot
    .getByRole("list", { name: "Earlier conversations" })
    .getByRole("button", { name: "Sign off on another one" })
    .click();
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "Sign off and pay" }).click();
  await expect(
    copilot.getByText("Done: CLM-1003 is paid $3,750.00."),
  ).toBeVisible();
  await expect(card).toHaveCount(0);
});

test("Cancel carries the turn on without signing off", async ({ page }) => {
  const copilot = sidebar(page);
  await ask(page, "Sign off CLM-1003");
  const card = copilot.getByRole("region", { name: "Confirm the sign-off" });
  await card.getByRole("button", { name: "Cancel" }).click();
  await expect(
    copilot.getByText(
      "I haven't signed off CLM-1003. What would you like instead?",
    ),
  ).toBeVisible();
});

test("a new conversation starts afresh, and an earlier one opens", async ({
  page,
}) => {
  const copilot = sidebar(page);
  await ask(page, "What needs me first?");
  await expect(copilot.getByRole("table")).toBeVisible();
  await copilot.getByRole("button", { name: "New conversation" }).click();
  await expect(copilot.getByText("Hello, Dana.")).toBeVisible();
  await copilot.getByRole("button", { name: "Earlier" }).click();
  await copilot
    .getByRole("list", { name: "Earlier conversations" })
    .getByRole("button", { name: "What needs me first?" })
    .click();
  await expect(copilot.getByRole("table")).toBeVisible();
});

test("the sidebar collapses to its tab, which the browser remembers", async ({
  page,
}) => {
  await sidebar(page)
    .getByRole("button", { name: "Collapse the Copilot" })
    .click();
  await expect(sidebar(page)).toHaveCount(0);
  await page.reload();
  await page.getByRole("button", { name: "Open the Copilot" }).click();
  await expect(sidebar(page)).toBeVisible();
});

test("on a narrow window the sidebar opens over the page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const box = await sidebar(page).boundingBox();
  expect(box?.x).toBe(0);
  await sidebar(page)
    .getByRole("button", { name: "Collapse the Copilot" })
    .click();
  await expect(
    page.getByRole("button", { name: "Open the Copilot" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "The claims queue" }),
  ).toBeVisible();
});
