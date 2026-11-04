import type { SyntheticEvent } from "react";
import { useState } from "react";
import { isSetUp, NOT_SET_UP, signIn } from "./auth";

/** The sign-in page: email and password. There's no sign-up. */
export function SignIn() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState(isSetUp() ? "" : NOT_SET_UP);
  const [busy, setBusy] = useState(false);

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    setBusy(true);
    setProblem("");
    void signIn(email, password).then((refusal) => {
      setBusy(false);
      if (refusal) setProblem(refusal);
    });
  };

  return (
    <main className="sign-in">
      <form className="panel sign-in-panel" onSubmit={submit}>
        <p className="brand">UnderCover</p>
        <h1>Sign in</h1>
        <p className="muted">
          For UnderCover&rsquo;s claims handlers. Ask your manager if you need
          an account.
        </p>
        <label>
          Email
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
            }}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
            }}
          />
        </label>
        {problem && <p role="alert">{problem}</p>}
        <button type="submit" disabled={busy || !isSetUp()}>
          {busy ? "Signing in" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
