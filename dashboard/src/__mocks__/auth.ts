// Supabase Auth in the tests: a handler is signed in without calling Supabase.
import type { Session } from "@supabase/supabase-js";
import { vi } from "vitest";
import { whoIsSignedIn } from "../testing";

export const NOT_SET_UP = "Sign-in isn't set up.";
export const WRONG_PASSWORD = "The email or password is wrong.";
export const AUTH_AWAY = "Sign-in isn't responding. Try again in a moment.";

export const isSetUp = () => true;
export const signIn = vi.fn(() => Promise.resolve(null));
export const signOut = vi.fn(() => Promise.resolve());

export function accessToken(): Promise<string | null> {
  const email = whoIsSignedIn();
  return Promise.resolve(email ? `token-for-${email}` : null);
}

export function useSession(): Session | null {
  const email = whoIsSignedIn();
  return email ? ({ user: { email } } as Session) : null;
}
