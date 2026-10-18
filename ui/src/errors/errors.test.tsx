import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetBridgeForTests } from "../bridge/client";
import { fail, installFakeBridge, pushBackendEvent, removeFakeBridge } from "../test/fakeBridge";
import { ErrorBoundary } from "./ErrorBoundary";
import {
  MAX_NOTICES,
  clearNoticesForTests,
  dismissNotice,
  pushNotice,
  useNotices,
} from "./notices";
import {
  describeError,
  handleUnexpectedError,
  installGlobalErrorHandlers,
  noticeFromCallError,
  reportClientError,
} from "./reporting";
import { BridgeCallError } from "../bridge/client";

beforeEach(() => {
  resetBridgeForTests();
  removeFakeBridge();
  clearNoticesForTests();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("notices", () => {
  it("keeps the newest few and can dismiss", () => {
    const { result } = renderHook(() => useNotices());
    act(() => {
      for (let i = 0; i < MAX_NOTICES + 2; i++) {
        pushNotice({ title: `n${i}`, message: "m", errorId: null, detail: null });
      }
    });
    expect(result.current).toHaveLength(MAX_NOTICES);
    expect(result.current[0]?.title).toBe("n2");
    const first = result.current[0];
    if (first === undefined) throw new Error("expected a notice");
    act(() => {
      dismissNotice(first.key);
    });
    expect(result.current).toHaveLength(MAX_NOTICES - 1);
  });
});

describe("describeError", () => {
  it("handles errors and other thrown values", () => {
    expect(describeError(new TypeError("bad")).message).toBe("TypeError: bad");
    expect(describeError({ a: 1 }).message).toBe('Non-error value thrown: {"a":1}');
    const circular: Record<string, unknown> = {};
    circular["self"] = circular;
    expect(describeError(circular).message).toContain("Non-error value thrown");
  });
});

describe("reporting", () => {
  it("logs to Python and returns the error ID", async () => {
    const api = installFakeBridge();
    await expect(reportClientError({ source: "window", message: "x" })).resolves.toBe("e1e2e3e4");
    expect(api.log_client_error).toHaveBeenCalledWith({ source: "window", message: "x" });
  });

  it("returns null when it can't reach Python", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    installFakeBridge({ log_client_error: () => fail("logging broke") });
    await expect(reportClientError({ source: "window", message: "x" })).resolves.toBeNull();
  });

  it("shows unexpected errors as a notice with the error ID", async () => {
    installFakeBridge();
    const { result } = renderHook(() => useNotices());
    await act(() => handleUnexpectedError(new Error("kaboom"), "promise"));
    expect(result.current[0]).toMatchObject({ errorId: "e1e2e3e4", detail: "Error: kaboom" });
  });

  it("shows failed Python calls with Python's report", () => {
    const { result } = renderHook(() => useNotices());
    act(() => {
      noticeFromCallError(
        new BridgeCallError("quit", { id: "f00d", kind: "expected", message: "No", detail: null }),
        "Quit failed",
      );
    });
    expect(result.current[0]).toMatchObject({
      title: "Quit failed",
      message: "No",
      errorId: "f00d",
    });
  });

  it("catches window errors, rejections and Python error events", async () => {
    installFakeBridge();
    const { result } = renderHook(() => useNotices());
    const stop = installGlobalErrorHandlers();
    try {
      act(() => {
        window.dispatchEvent(new ErrorEvent("error", { error: new Error("from window") }));
        const rejection = new Event("unhandledrejection") as PromiseRejectionEvent;
        Object.defineProperty(rejection, "reason", { value: new Error("from promise") });
        window.dispatchEvent(rejection);
        pushBackendEvent({
          name: "app:error",
          payload: { id: "py01", kind: "unexpected", message: "Python failed", detail: "X" },
        });
      });
      await waitFor(() => {
        expect(result.current).toHaveLength(3);
      });
      const details = result.current.map((n) => n.detail);
      expect(details).toEqual(
        expect.arrayContaining(["Error: from window", "Error: from promise", "X"]),
      );
    } finally {
      stop();
    }
  });
});

function Bomb(): never {
  throw new Error("render failure");
}

describe("ErrorBoundary", () => {
  it("shows a readable page with the error ID instead of a blank window", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const api = installFakeBridge();
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    expect(screen.getByLabelText("Details")).toHaveValue("Error: render failure");
    await screen.findByText("Error ID e1e2e3e4.");
    expect(api.log_client_error).toHaveBeenCalledWith(
      expect.objectContaining({ source: "render", message: "Error: render failure" }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Open log folder" }));
    expect(api.open_log_folder).toHaveBeenCalled();
  });

  it("says so when the error couldn't be logged", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    installFakeBridge({ log_client_error: () => fail("no log") });
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    await screen.findByText("The error couldn't be written to the log.");
  });

  it("renders children when nothing fails", () => {
    render(
      <ErrorBoundary>
        <p>fine</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("fine")).toBeInTheDocument();
  });
});
