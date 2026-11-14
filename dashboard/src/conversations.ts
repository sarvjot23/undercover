// The Copilot's conversations as the app keeps them, and what the sidebar sends.
import { useState } from "react";
import type { SourceFile } from "./api";
import { postForResult } from "./api";
import { freshToken } from "./auth";
import { cost, duration } from "./format";

export type StepKind =
  "claims" | "customers" | "context" | "work" | "memory" | "action";
export type StepState = "working" | "done" | "refused" | "failed";

/** One of the Copilot's steps, as its card shows it. */
export interface CopilotStep {
  step_id: number;
  key: string;
  kind: StepKind;
  tool: string;
  input: string;
  state: StepState;
  started_at: string;
  seconds: number;
  asked: string;
  answer: string;
  reason: string;
  sources: SourceFile[];
}

/** What the confirmation card shows, read from our records. */
export interface Confirmation {
  claim_id: string;
  customer: string;
  amount: number;
  reason: string;
  policy_section: string;
}

export type TurnStatus = "working" | "waiting" | "done" | "failed" | "stopped";

export interface Turn {
  turn_id: number;
  message: string;
  status: TurnStatus;
  started_at: string;
  answered_at: string | null;
  ended_at: string | null;
  answer: string | null;
  model_calls: number | null;
  cost: number | null;
  error: string | null;
  confirmation: Confirmation | null;
  steps: CopilotStep[];
}

export interface Conversation {
  conversation_id: string;
  title: string;
  started_at: string;
  turns: Turn[];
}

export interface ConversationSummary {
  conversation_id: string;
  handler_id: string;
  title: string;
  started_at: string;
}

export const SUGGESTIONS = [
  "What needs me today?",
  "Work the queue and tell me what needs me.",
  "Are we meeting the success criteria we agreed?",
];

/** The turn a conversation is on, if any. */
export function lastTurn(conversation?: Conversation): Turn | undefined {
  return conversation?.turns.at(-1);
}

/** Whether the Copilot is working on a turn of this conversation. */
export function isWorking(conversation?: Conversation): boolean {
  return lastTurn(conversation)?.status === "working";
}

/** The confirmation the conversation waits on, if any. */
export function waitingFor(conversation?: Conversation): Confirmation | null {
  const turn = lastTurn(conversation);
  return turn?.status === "waiting" ? turn.confirmation : null;
}

/** Turn each claim id in an answer into a link to the claim's page. */
export function linkClaims(markdown: string): string {
  return markdown.replace(
    /(?<![[\w/#-])(CLM-\d{4})(?![\w\]-])/g,
    "[$1](#/claims/$1)",
  );
}

/** The seconds between two times, or from one time to now. */
export function secondsBetween(from: string, to?: string | null): number {
  const end = to ? Date.parse(to) : Date.now();
  return Math.max(0, (end - Date.parse(from)) / 1000);
}

/** The small print under an answer: model calls, their cost and the time. */
export function turnLine(turn: Turn): string {
  const calls = turn.model_calls ?? 0;
  const began = turn.answered_at ?? turn.started_at;
  return [
    `${String(calls)} model ${calls === 1 ? "call" : "calls"}`,
    cost(turn.cost ?? 0),
    duration(secondsBetween(began, turn.ended_at)),
  ].join(" · ");
}

export type Sent =
  | { conversation: Conversation; refusal?: undefined }
  | { conversation?: undefined; refusal: string };

/** Send the Copilot a message, starting a conversation when there's none yet. */
export async function ask(
  conversationId: string | null,
  message: string,
): Promise<Sent> {
  await freshToken();
  const path = conversationId
    ? `/api/conversations/${conversationId}/messages`
    : "/api/conversations";
  const sent = await postForResult(path, { message });
  return "refusal" in sent
    ? { refusal: sent.refusal }
    : { conversation: sent.data as Conversation };
}

/** The handler's answer to the confirmation card. */
export async function confirm(
  conversationId: string,
  confirmed: boolean,
): Promise<Sent> {
  await freshToken();
  const sent = await postForResult(
    `/api/conversations/${conversationId}/confirmation`,
    { confirmed },
  );
  return "refusal" in sent
    ? { refusal: sent.refusal }
    : { conversation: sent.data as Conversation };
}

const OPEN_KEY = "undercover-copilot";

/** Whether the sidebar is open: open the first time, then as the handler left
 * it in this browser. */
export function useCopilotOpen(): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(OPEN_KEY) !== "closed";
    } catch {
      return true;
    }
  });
  const change = (next: boolean) => {
    setOpen(next);
    try {
      localStorage.setItem(OPEN_KEY, next ? "open" : "closed");
    } catch {
      // The choice lasts only this visit.
    }
  };
  return [open, change];
}

/** What the message box says: answer the card first, wait, or ask. */
export function boxPlaceholder(waiting: boolean, working: boolean): string {
  if (waiting) return "Answer the confirmation first";
  if (working) return "The Copilot is working";
  return "Ask the Copilot";
}
