import type { Status } from "./api";
import { STATUS_LABELS } from "./format";
import type { Tone } from "./ui";
import { Badge } from "./ui";

// Gold, Champagne and Antique side by side, then Steel and Burnished, as BRAND.md has it.
const TONES: Record<Status, Tone> = {
  waiting: "gold",
  in_progress: "champagne",
  awaiting_sign_off: "antique",
  decided: "steel",
  needs_handler: "burnished",
};

export function StatusBadge({ status }: Readonly<{ status: Status }>) {
  return <Badge tone={TONES[status]}>{STATUS_LABELS[status]}</Badge>;
}
