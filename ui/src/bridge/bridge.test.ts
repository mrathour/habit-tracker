import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fail,
  installFakeBridge,
  ok,
  pushBackendEvent,
  removeFakeBridge,
} from "../test/fakeBridge";
import {
  BridgeCallError,
  BridgeUnavailableError,
  callPython,
  resetBridgeForTests,
  waitForBridge,
} from "./client";
import { DOM_EVENT_NAME, onBackendEvent } from "./events";
import type { PythonApi } from "./types";

beforeEach(() => {
  resetBridgeForTests();
  removeFakeBridge();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("waitForBridge", () => {
  it("resolves at once when the API is already injected", async () => {
    const api = installFakeBridge();
    await expect(waitForBridge()).resolves.toBe(api);
  });

  it("waits for the pywebviewready event", async () => {
    const pending = waitForBridge();
    const api = installFakeBridge();
    window.dispatchEvent(new Event("pywebviewready"));
    await expect(pending).resolves.toBe(api);
  });

  it("ignores pywebviewready before the API has methods", async () => {
    vi.useFakeTimers();
    const pending = waitForBridge(1000);
    window.pywebview = { api: {} };
    window.dispatchEvent(new Event("pywebviewready"));
    vi.advanceTimersByTime(1000);
    await expect(pending).rejects.toBeInstanceOf(BridgeUnavailableError);
  });

  it("gives up after the timeout and can be retried", async () => {
    vi.useFakeTimers();
    const pending = waitForBridge(500);
    vi.advanceTimersByTime(500);
    await expect(pending).rejects.toBeInstanceOf(BridgeUnavailableError);
    const api = installFakeBridge();
    await expect(waitForBridge()).resolves.toBe(api);
  });
});

describe("callPython", () => {
  it("unwraps a successful response", async () => {
    const api = installFakeBridge();
    await expect(callPython("run_bridge_check", 3)).resolves.toEqual({ run_id: "run-1", steps: 3 });
    expect(api.run_bridge_check).toHaveBeenCalledWith(3);
  });

  it("throws BridgeCallError with the Python report", async () => {
    installFakeBridge({ get_app_info: () => fail("Database is damaged", "deadbeef") });
    const error: unknown = await callPython("get_app_info").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(BridgeCallError);
    const callError = error as BridgeCallError;
    expect(callError.message).toBe("Database is damaged");
    expect(callError.report.id).toBe("deadbeef");
    expect(callError.method).toBe("get_app_info");
  });

  it("rejects a malformed response", async () => {
    installFakeBridge({
      quit: (() => Promise.resolve(undefined)) as unknown as PythonApi["quit"],
    });
    await expect(callPython("quit")).rejects.toThrow("unexpected response");
  });

  it("passes on a rejection from pywebview itself", async () => {
    installFakeBridge({ ui_ready: () => Promise.reject(new Error("bridge broke")) });
    await expect(callPython("ui_ready")).rejects.toThrow("bridge broke");
  });

  it("keeps successful falsy data", async () => {
    installFakeBridge({ ui_ready: () => ok(null) });
    await expect(callPython("ui_ready")).resolves.toBeNull();
  });
});

describe("onBackendEvent", () => {
  it("delivers only the named event", () => {
    const progress = vi.fn();
    const stop = onBackendEvent("bridge-check:progress", progress);
    pushBackendEvent({ name: "bridge-check:done", payload: { run_id: "r", elapsed_ms: 1 } });
    pushBackendEvent({
      name: "bridge-check:progress",
      payload: { run_id: "r", step: 1, steps: 2, thread: "t" },
    });
    expect(progress).toHaveBeenCalledTimes(1);
    expect(progress).toHaveBeenCalledWith({ run_id: "r", step: 1, steps: 2, thread: "t" });
    stop();
    pushBackendEvent({
      name: "bridge-check:progress",
      payload: { run_id: "r", step: 2, steps: 2, thread: "t" },
    });
    expect(progress).toHaveBeenCalledTimes(1);
  });

  it("ignores malformed events", () => {
    const handler = vi.fn();
    onBackendEvent("app:error", handler);
    window.dispatchEvent(new CustomEvent(DOM_EVENT_NAME, { detail: null }));
    window.dispatchEvent(new CustomEvent(DOM_EVENT_NAME, { detail: { payload: 1 } }));
    window.dispatchEvent(new CustomEvent(DOM_EVENT_NAME, { detail: "app:error" }));
    expect(handler).not.toHaveBeenCalled();
  });
});
