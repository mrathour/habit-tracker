import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { resetBridgeForTests } from "./bridge/client";
import { clearNoticesForTests } from "./errors/notices";
import {
  appInfo,
  fail,
  installFakeBridge,
  ok,
  pushBackendEvent,
  removeFakeBridge,
} from "./test/fakeBridge";

beforeEach(() => {
  resetBridgeForTests();
  removeFakeBridge();
  clearNoticesForTests();
});

describe("App", () => {
  it("shows the details Python sends and reports ready", async () => {
    const api = installFakeBridge();
    render(<App />);
    expect(screen.getByText("Connecting to the app…")).toBeInTheDocument();
    await screen.findByText(/Connected\./);
    expect(screen.getByText(appInfo.database_path)).toBeInTheDocument();
    expect(screen.getByText("Dev mode · v0.1.0")).toBeInTheDocument();
    await waitFor(() => {
      expect(api.ui_ready).toHaveBeenCalled();
    });
  });

  it("explains when it isn't running inside the app", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<App />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(screen.getByText(/isn.t running inside the Habit Tracker window/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows a Python failure with its error ID", async () => {
    installFakeBridge({ get_app_info: () => fail("Python broke", "c0ffee00") });
    render(<App />);
    await screen.findByText(/Python couldn.t send the app.s details: Python broke/);
    expect(screen.getByText(/error ID c0ffee00/)).toBeInTheDocument();
  });

  it("follows the bridge check's progress events", async () => {
    const api = installFakeBridge();
    render(<App />);
    const start = await screen.findByRole("button", { name: "Run bridge check" });
    expect(screen.getByText(/No events yet/)).toBeInTheDocument();
    await userEvent.click(start);
    expect(api.run_bridge_check).toHaveBeenCalledWith(5);

    act(() => {
      for (let step = 1; step <= 5; step++) {
        pushBackendEvent({
          name: "bridge-check:progress",
          payload: { run_id: "run-1", step, steps: 5, thread: "bridge-check-run-1" },
        });
      }
      pushBackendEvent({
        name: "bridge-check:done",
        payload: { run_id: "run-1", elapsed_ms: 2000 },
      });
    });

    expect(await screen.findByText("Received all 5 steps in 2000 ms")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    const log = screen.getByRole("list");
    expect(within(log).getAllByRole("listitem")).toHaveLength(6);
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
  });

  it("ignores events from another run", async () => {
    installFakeBridge();
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Run bridge check" }));
    act(() => {
      pushBackendEvent({
        name: "bridge-check:progress",
        payload: { run_id: "someone-else", step: 1, steps: 5, thread: "t" },
      });
    });
    expect(screen.getByText(/No events yet/)).toBeInTheDocument();
  });

  it("accepts progress that arrives before the call returns", async () => {
    let finish: (() => void) | undefined;
    installFakeBridge({
      run_bridge_check: (steps: number) =>
        new Promise((resolve) => {
          finish = () => {
            void ok({ run_id: "early", steps }).then(resolve);
          };
        }),
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Run bridge check" }));
    act(() => {
      pushBackendEvent({
        name: "bridge-check:progress",
        payload: { run_id: "early", step: 1, steps: 5, thread: "t" },
      });
    });
    expect(await screen.findByText("Step 1 of 5")).toBeInTheDocument();
    act(() => {
      finish?.();
    });
    await waitFor(() => {
      expect(screen.getByText("Step 1 of 5")).toBeInTheDocument();
    });
  });

  it("shows a banner when the bridge check can't start", async () => {
    installFakeBridge({ run_bridge_check: () => fail("A bridge check is already running.") });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Run bridge check" }));
    expect(await screen.findByText("The bridge check couldn't start")).toBeInTheDocument();
    expect(screen.getByText("A bridge check is already running.")).toBeInTheDocument();
  });

  it("hides diagnostics unless Python enables them", async () => {
    installFakeBridge({
      get_app_info: () => ok({ ...appInfo, mode: "normal", diagnostics: false }),
    });
    render(<App />);
    await screen.findByText("Normal mode · v0.1.0");
    expect(screen.queryByText("Diagnostics")).not.toBeInTheDocument();
  });

  it("shows diagnostics Python call failures as banners", async () => {
    installFakeBridge({ raise_test_error: () => fail("Something went wrong.", "beef0001") });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Error in a Python call" }));
    expect(await screen.findByText("A Python call failed")).toBeInTheDocument();
    expect(screen.getByText("Error ID beef0001")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("A Python call failed")).not.toBeInTheDocument();
  });

  it("opens the log folder", async () => {
    const api = installFakeBridge();
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Open" }));
    expect(api.open_log_folder).toHaveBeenCalled();
  });
});
