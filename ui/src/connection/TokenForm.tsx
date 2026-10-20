import { useId, useState, type SyntheticEvent } from "react";

import { BridgeCallError, callPython } from "../bridge/client";
import type { ConnectionInfo, PastedKind } from "../bridge/types";
import { problemFrom, type Problem } from "./problems";

const PORTAL_URL = "https://www.notion.so/developers";
const TOKENS_URL = "https://www.notion.so/developers/tokens";

const KINDS: { kind: PastedKind; label: string; hint: string }[] = [
  {
    kind: "internal",
    label: "Internal integration token",
    hint: "Recommended. You choose exactly which pages it can read, and it can be limited to reading.",
  },
  {
    kind: "pat",
    label: "Personal access token",
    hint: "Reads everything you can see in Notion, with no sharing step. It expires on the date you chose.",
  },
];

function openExternal(url: string): void {
  void callPython("open_external", url).catch(() => undefined);
}

/**
 * Connect with a pasted token (PLAN.md 12.4). Python checks it with Notion before saving
 * anything; the token is never shown again or kept in the page after submitting.
 */
export function TokenForm({
  onConnected,
  onCancel,
  replacing,
}: {
  onConnected: (info: ConnectionInfo) => void;
  onCancel?: () => void;
  /** Name of the current connection, when this replaces it. */
  replacing?: string | null;
}) {
  const id = useId();
  const [kind, setKind] = useState<PastedKind>("internal");
  const [token, setToken] = useState("");
  const [visible, setVisible] = useState(false);
  const [checking, setChecking] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);

  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (checking) return;
    setChecking(true);
    setFieldError(null);
    setProblem(null);
    callPython("connect_with_token", kind, token)
      .then((info) => {
        setToken("");
        onConnected(info);
      })
      .catch((error: unknown) => {
        if (error instanceof BridgeCallError && error.report.code === "invalid_token") {
          setFieldError(error.report.message);
        } else {
          setProblem(problemFrom(error));
        }
      })
      .finally(() => {
        setChecking(false);
      });
  };

  return (
    <form className="column" onSubmit={submit} noValidate>
      <fieldset className="choices">
        <legend className="visually-hidden">Kind of token</legend>
        {KINDS.map((option) => (
          <label key={option.kind} className="choice">
            <input
              type="radio"
              name={`${id}-kind`}
              value={option.kind}
              checked={kind === option.kind}
              onChange={() => {
                setKind(option.kind);
              }}
            />
            <span>{option.label}</span>
            <span className="hint">{option.hint}</span>
          </label>
        ))}
      </fieldset>

      {kind === "internal" ? (
        <ol className="steps">
          <li>
            In{" "}
            <button
              type="button"
              className="link-button"
              onClick={() => {
                openExternal(PORTAL_URL);
              }}
            >
              Notion&apos;s developer portal
            </button>
            , create an internal connection with <strong>Read content</strong> only.
          </li>
          <li>Copy its token and paste it below.</li>
          <li>
            In Notion, open your work log, click <strong>•••</strong>, then <strong>More</strong>,
            then <strong>Add connections</strong>, and choose your connection.
          </li>
        </ol>
      ) : (
        <ol className="steps">
          <li>
            In Notion&apos;s developer portal, open{" "}
            <button
              type="button"
              className="link-button"
              onClick={() => {
                openExternal(TOKENS_URL);
              }}
            >
              Personal access tokens
            </button>{" "}
            and click <strong>New token</strong>.
          </li>
          <li>
            Name it, choose when it expires, create it, and copy it. Notion shows it only once.
          </li>
          <li>Paste it below. Habit Tracker only reads your work log with it.</li>
        </ol>
      )}

      <div className="field">
        <label htmlFor={`${id}-token`}>Token</label>
        <div className="input-row">
          <input
            id={`${id}-token`}
            className="input"
            type={visible ? "text" : "password"}
            autoComplete="off"
            spellCheck={false}
            value={token}
            aria-invalid={fieldError !== null}
            aria-describedby={fieldError ? `${id}-error` : undefined}
            onChange={(event) => {
              setToken(event.target.value);
              setFieldError(null);
            }}
          />
          <button
            type="button"
            className="button"
            aria-pressed={visible}
            onClick={() => {
              setVisible((v) => !v);
            }}
          >
            {visible ? "Hide" : "Show"}
          </button>
        </div>
        {fieldError && (
          <p id={`${id}-error`} className="field-error" role="alert">
            {fieldError}
          </p>
        )}
      </div>

      {replacing && (
        <p className="small muted">
          This replaces the current connection to {replacing}. If it used Notion sign-in, that
          access is revoked first.
        </p>
      )}

      {problem && (
        <div className={`notice ${problem.tone}`} role="alert">
          <strong>{problem.title}</strong>
          <p>{problem.message}</p>
          {problem.errorId && <p className="small muted">Error ID {problem.errorId}</p>}
        </div>
      )}

      <div className="actions">
        <button type="submit" className="button primary" disabled={checking || token.trim() === ""}>
          {checking && <span className="spinner" aria-hidden="true" />}
          {checking ? "Checking with Notion…" : "Check and connect"}
        </button>
        {onCancel && (
          <button type="button" className="link-button" onClick={onCancel} disabled={checking}>
            Back
          </button>
        )}
      </div>
    </form>
  );
}
