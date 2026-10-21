import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { parseRoute, useJson, useRoute } from "./hooks";
import { stubBackend } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.location.hash = "";
});

it("parses each route", () => {
  expect(parseRoute("")).toEqual({ view: "queue" });
  expect(parseRoute("#/")).toEqual({ view: "queue" });
  expect(parseRoute("#/claims/CLM-1001")).toEqual({
    view: "claim",
    claimId: "CLM-1001",
  });
  expect(parseRoute("#/instructions")).toEqual({ view: "instructions" });
  expect(parseRoute("#/live")).toEqual({ view: "live" });
  expect(parseRoute("#/nowhere")).toEqual({ view: "queue" });
});

it("follows the hash", async () => {
  const { result } = renderHook(() => useRoute());
  act(() => {
    window.location.hash = "#/instructions";
  });
  await waitFor(() => {
    expect(result.current).toEqual({ view: "instructions" });
  });
});

it("loads JSON and reports errors", async () => {
  stubBackend({ "/api/a": { ok: 1 } });
  const ok = renderHook(() => useJson<{ ok: number }>("/api/a"));
  await waitFor(() => {
    expect(ok.result.current.data).toEqual({ ok: 1 });
  });
  const missing = renderHook(() => useJson("/api/b"));
  await waitFor(() => {
    expect(missing.result.current.error).toBe(true);
  });
});

it("polls and reloads", async () => {
  const fetchMock = stubBackend({ "/api/a": { ok: 1 } });
  const { result } = renderHook(() => useJson("/api/a", 50));
  await waitFor(() => {
    expect(fetchMock.mock.calls.length).toBeGreaterThan(2);
  });
  const calls = fetchMock.mock.calls.length;
  act(() => {
    result.current.reload();
  });
  await waitFor(() => {
    expect(fetchMock.mock.calls.length).toBeGreaterThan(calls);
  });
});

it("polls while the data asks for it", async () => {
  const routes: Record<string, unknown> = { "/api/a": { more: true } };
  const fetchMock = stubBackend(routes);
  const every = (data: { more: boolean }) => (data.more ? 20 : 0);
  const { result } = renderHook(() => useJson("/api/a", every));
  await waitFor(() => {
    expect(fetchMock.mock.calls.length).toBeGreaterThan(2);
  });
  routes["/api/a"] = { more: false };
  await waitFor(() => {
    expect(result.current.data).toEqual({ more: false });
  });
  const calls = fetchMock.mock.calls.length;
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fetchMock.mock.calls).toHaveLength(calls);
});
