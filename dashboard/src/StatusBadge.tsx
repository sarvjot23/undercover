import type { Status } from "./api";
import { STATUS_LABELS } from "./format";
import type { Tone } from "./ui";
import { Badge } from "./ui";

// The same colors the live view gives a claim waiting for sign-off (Burnished, the
// alert) and one left for a handler (Champagne), on every page. A claim sent back
// waits for the agent, as a waiting claim does.
const TONES: Record<Status, Tone> = {
  waiting: "antique",
  in_progress: "gold",
  awaiting_sign_off: "burnished",
  sent_back: "antique",
  decided: "steel",
  needs_handler: "champagne",
};

export function StatusBadge({ status }: Readonly<{ status: Status }>) {
  return <Badge tone={TONES[status]}>{STATUS_LABELS[status]}</Badge>;
}
