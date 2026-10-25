import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "../App";
import { resetBridgeForTests } from "../bridge/client";
import { clearNoticesForTests } from "../errors/notices";
import {
  connectedWithDatabase,
  fail,
  installFakeBridge,
  ok,
  policyNotice,
  removeFakeBridge,
} from "../test/fakeBridge";

beforeEach(() => {
  resetBridgeForTests();
  removeFakeBridge();
  clearNoticesForTests();
});

describe("privacy policy notice", () => {
  it("shows every change before anything else and starts nothing until continued", async () => {
    const api = installFakeBridge({
      get_policy_notice: () => ok(policyNotice),
      get_connection: () => ok(connectedWithDatabase),
    });
    render(<App />);
    const heading = await screen.findByRole("heading", { name: "The privacy policy has changed" });
    await waitFor(() => {
      expect(heading).toHaveFocus();
    });
    expect(screen.getByText("Logs are kept for 30 days instead of 60.")).toBeInTheDocument();
    expect(screen.getByText("The app checks GitHub for new versions.")).toBeInTheDocument();
    expect(screen.getByText("You can turn this off in Settings.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Version 2 · / })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Version 3 · / })).toBeInTheDocument();
    // Nothing behind it: no navigation, no Home, no sync.
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
    expect(api.start_sync).not.toHaveBeenCalled();
    expect(api.get_sync_status).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(api.acknowledge_policy).toHaveBeenCalledWith(3);
    await waitFor(() => {
      expect(screen.queryByText("The privacy policy has changed")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(api.start_sync).toHaveBeenCalledWith("auto");
    });
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });

  it("opens the full policy in the browser only when asked", async () => {
    const api = installFakeBridge({ get_policy_notice: () => ok(policyNotice) });
    render(<App />);
    await screen.findByRole("heading", { name: "The privacy policy has changed" });
    expect(api.open_external).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Read the full privacy policy" }));
    expect(api.open_external).toHaveBeenCalledWith(policyNotice.url);
  });

  it("closes the app without acknowledging", async () => {
    const api = installFakeBridge({ get_policy_notice: () => ok(policyNotice) });
    render(<App />);
    await screen.findByRole("heading", { name: "The privacy policy has changed" });
    await userEvent.click(screen.getByRole("button", { name: "Close the app" }));
    expect(api.quit).toHaveBeenCalled();
    expect(api.acknowledge_policy).not.toHaveBeenCalled();
  });

  it("keeps the notice when the answer can't be saved", async () => {
    const api = installFakeBridge({
      get_policy_notice: () => ok(policyNotice),
      get_connection: () => ok(connectedWithDatabase),
      acknowledge_policy: () => fail("Database locked", "5a5a5a5a"),
    });
    render(<App />);
    await screen.findByRole("heading", { name: "The privacy policy has changed" });
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Your answer couldn't be saved")).toBeInTheDocument();
    expect(within(alert).getByText(/Error ID 5a5a5a5a/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "The privacy policy has changed" })).toBeVisible();
    expect(api.start_sync).not.toHaveBeenCalled();

    api.acknowledge_policy.mockImplementation(() => ok(null));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => {
      expect(api.start_sync).toHaveBeenCalledWith("auto");
    });
  });

  it("waits, with a retry, when the notice can't be read", async () => {
    const api = installFakeBridge({
      get_policy_notice: () => fail("Database locked", "6b6b6b6b"),
      get_connection: () => ok(connectedWithDatabase),
    });
    render(<App />);
    expect(
      await screen.findByText("The app couldn't check for privacy policy changes"),
    ).toBeInTheDocument();
    expect(screen.getByText("Error ID 6b6b6b6b")).toBeInTheDocument();
    expect(api.start_sync).not.toHaveBeenCalled();

    api.get_policy_notice.mockImplementation(() => ok(null));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(api.start_sync).toHaveBeenCalledWith("auto");
    });
  });

  it("shows nothing when there is no notice", async () => {
    const api = installFakeBridge();
    render(<App />);
    await screen.findByRole("heading", { name: "See where your working hours go" });
    expect(screen.queryByText("The privacy policy has changed")).not.toBeInTheDocument();
    expect(api.acknowledge_policy).not.toHaveBeenCalled();
  });
});

describe("privacy policy links", () => {
  it("are on the Connect screen", async () => {
    const api = installFakeBridge();
    render(<App />);
    await screen.findByRole("heading", { name: "See where your working hours go" });
    await userEvent.click(screen.getByRole("button", { name: "Privacy policy" }));
    expect(api.open_external).toHaveBeenCalledWith(
      "https://habit-tracker.mrathour.workers.dev/privacy",
    );
    await userEvent.click(screen.getByRole("button", { name: "Terms of use" }));
    expect(api.open_external).toHaveBeenCalledWith(
      "https://habit-tracker.mrathour.workers.dev/terms",
    );
  });

  it("and in Settings, with this build's policy version", async () => {
    const api = installFakeBridge();
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
    expect(await screen.findByText("Version 1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Read the privacy policy" }));
    expect(api.open_external).toHaveBeenCalledWith(
      "https://habit-tracker.mrathour.workers.dev/privacy",
    );
  });
});
