import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { accessToken, signOut } from "./auth";
import { dana, pathOf, stubBackend, summary } from "./testing";

// Supabase Auth as the dashboard sees it, from the address the tests set.
const TOKEN_URL = "http://supabase.test/auth/v1/token?grant_type=password";

afterEach(async () => {
  await signOut();
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

function session(email: string) {
  return {
    access_token: `token-for-${email}`,
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: "refresh",
    user: {
      id: "user-1",
      aud: "authenticated",
      role: "authenticated",
      email,
      app_metadata: {},
      user_metadata: {},
      created_at: "2026-11-04T00:00:00Z",
    },
  };
}

function fillIn(email: string, password: string) {
  fireEvent.change(screen.getByLabelText("Email"), {
    target: { value: email },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

it("signs a handler in and shows the queue, with no sign-up", async () => {
  const fetchMock = stubBackend({
    [`POST ${TOKEN_URL}`]: session(dana.email),
    "/api/claims": [summary()],
    "/api/handlers": [dana],
  });
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeDefined();
  expect(screen.queryByText(/sign up/i)).toBeNull();
  expect(screen.queryByRole("link")).toBeNull();

  fillIn(dana.email, "the password");
  expect(await screen.findByText("Dana Whitfield")).toBeDefined();
  expect(await screen.findByRole("link", { name: "CLM-1001" })).toBeDefined();
  const signedIn = fetchMock.mock.calls.find(
    ([input]) => pathOf(input) === TOKEN_URL,
  );
  expect(JSON.parse(signedIn?.[1]?.body as string)).toMatchObject({
    email: dana.email,
    password: "the password",
  });
  expect(await accessToken()).toBe(`token-for-${dana.email}`);
});

it("says when the email or password is wrong", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            code: "invalid_credentials",
            msg: "Invalid login credentials",
          }),
          { status: 400 },
        ),
      ),
    ),
  );
  render(<App />);
  await screen.findByRole("heading", { name: "Sign in" });
  fillIn(dana.email, "wrong");
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The email or password is wrong.",
  );
  expect(await accessToken()).toBeNull();
});

it("says when sign-in can't be reached", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  render(<App />);
  await screen.findByRole("heading", { name: "Sign in" });
  fillIn(dana.email, "the password");
  await waitFor(() => {
    expect(screen.getByRole("alert").textContent).toBe(
      "Sign-in isn't responding. Try again in a moment.",
    );
  });
});
