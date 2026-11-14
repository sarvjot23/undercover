// The only module that reaches Supabase: handlers sign in with Supabase Auth.
import type { Session, SupabaseClient } from "@supabase/supabase-js";
import { AuthApiError, createClient } from "@supabase/supabase-js";
import { useEffect, useState } from "react";

export const NOT_SET_UP =
  "Sign-in isn't set up: add VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY to .env.";
export const WRONG_PASSWORD = "The email or password is wrong.";
export const AUTH_AWAY = "Sign-in isn't responding. Try again in a moment.";

let client: SupabaseClient | undefined;

export function isSetUp(): boolean {
  return Boolean(
    import.meta.env.VITE_SUPABASE_URL &&
    import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
  );
}

function supabase(): SupabaseClient {
  client ??= createClient(
    import.meta.env.VITE_SUPABASE_URL ?? "",
    import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? "",
    { auth: { storageKey: "undercover-session" } },
  );
  return client;
}

/** Sign in with an email and password; return what went wrong, or null. */
export async function signIn(
  email: string,
  password: string,
): Promise<string | null> {
  const { error } = await supabase().auth.signInWithPassword({
    email,
    password,
  });
  if (!error) return null;
  return error instanceof AuthApiError && error.status === 400
    ? WRONG_PASSWORD
    : AUTH_AWAY;
}

export async function signOut(): Promise<void> {
  await supabase().auth.signOut();
}

/** The signed-in handler's access token, for the backend to check. */
export async function accessToken(): Promise<string | null> {
  if (!isSetUp()) return null;
  const { data } = await supabase().auth.getSession();
  return data.session?.access_token ?? null;
}

/** Supabase's sign-ins last an hour; renew one with less than this left. */
export const RENEW_WITHIN_SECONDS = 20 * 60;

/** Whether a session ending at this time, in seconds, should be renewed now. */
export function needsRenewal(
  expiresAt: number | undefined,
  now = Date.now() / 1000,
): boolean {
  return expiresAt === undefined || expiresAt - now < RENEW_WITHIN_SECONDS;
}

/**
 * Renew the handler's sign-in when it has less than 20 minutes left, before a
 * message to the Copilot or an answer to its confirmation: the Copilot works with
 * it for as long as a turn takes.
 */
export async function freshToken(): Promise<void> {
  if (!isSetUp()) return;
  const { data } = await supabase().auth.getSession();
  if (data.session && needsRenewal(data.session.expires_at)) {
    await supabase().auth.refreshSession();
  }
}

/** The session: undefined while it loads, null when nobody is signed in. */
export function useSession(): Session | null | undefined {
  const [session, setSession] = useState<Session | null | undefined>(() =>
    isSetUp() ? undefined : null,
  );
  useEffect(() => {
    if (!isSetUp()) return;
    const { data } = supabase().auth.onAuthStateChange((_, changed) => {
      setSession(changed);
    });
    return () => {
      data.subscription.unsubscribe();
    };
  }, []);
  return session;
}
