import { createContext, useContext } from "react";
import type { Handler } from "./api";

/** The handler signed in, once the dashboard has found them by email. */
export const HandlerContext = createContext<Handler | null>(null);

export function useHandler(): Handler | null {
  return useContext(HandlerContext);
}

/** Whether the handler signed in can sign off payouts over the limit. */
export function useCanApprove(): boolean {
  return useHandler()?.can_approve_over_limit ?? false;
}

export const ONLY_APPROVERS =
  "Only a handler who can sign off payouts over the limit";
