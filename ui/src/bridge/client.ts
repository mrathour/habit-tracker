import type { BridgeResponse, ErrorReport, PythonApi } from "./types";

declare global {
  interface Window {
    pywebview?: { api: Partial<PythonApi> };
  }
}

/** How long to wait for pywebview to inject its API before deciding we're not in the app. */
export const BRIDGE_TIMEOUT_MS = 10_000;

/** The page isn't running inside the desktop app (for example, it was opened in a browser). */
export class BridgeUnavailableError extends Error {
  override name = "BridgeUnavailableError";
  constructor() {
    super("The desktop app's bridge isn't available. Open this page from Habit Tracker.");
  }
}

/** A Python method returned an error. `report` is already logged on the Python side. */
export class BridgeCallError extends Error {
  override name = "BridgeCallError";
  constructor(
    readonly method: string,
    readonly report: ErrorReport,
  ) {
    super(report.message);
  }
}

function hasApi(api: Partial<PythonApi> | undefined): api is PythonApi {
  return typeof api?.get_app_info === "function";
}

let bridgePromise: Promise<PythonApi> | null = null;

/** Resolves with the Python API once pywebview has injected it. */
export function waitForBridge(timeoutMs: number = BRIDGE_TIMEOUT_MS): Promise<PythonApi> {
  bridgePromise ??= new Promise<PythonApi>((resolve, reject) => {
    const current = window.pywebview?.api;
    if (hasApi(current)) {
      resolve(current);
      return;
    }
    const onReady = () => {
      const api = window.pywebview?.api;
      if (hasApi(api)) {
        window.clearTimeout(timer);
        window.removeEventListener("pywebviewready", onReady);
        resolve(api);
      }
    };
    const timer = window.setTimeout(() => {
      window.removeEventListener("pywebviewready", onReady);
      bridgePromise = null;
      reject(new BridgeUnavailableError());
    }, timeoutMs);
    window.addEventListener("pywebviewready", onReady);
  });
  return bridgePromise;
}

/** Forget the cached bridge. Only for tests. */
export function resetBridgeForTests(): void {
  bridgePromise = null;
}

type ApiMethod = keyof PythonApi;
type ResponseData<M extends ApiMethod> =
  Awaited<ReturnType<PythonApi[M]>> extends BridgeResponse<infer T> ? T : never;

/** Call a Python method and unwrap its response, throwing {@link BridgeCallError} on failure. */
export async function callPython<M extends ApiMethod>(
  method: M,
  ...args: Parameters<PythonApi[M]>
): Promise<ResponseData<M>> {
  const api = await waitForBridge();
  const fn = api[method] as (...a: Parameters<PythonApi[M]>) => Promise<unknown>;
  const response = (await fn.apply(api, args)) as BridgeResponse<ResponseData<M>> | undefined;
  if (response === undefined || typeof response !== "object" || !("ok" in response)) {
    throw new Error(`Python method ${method}() returned an unexpected response`);
  }
  if (!response.ok) {
    throw new BridgeCallError(method, response.error);
  }
  return response.data;
}
