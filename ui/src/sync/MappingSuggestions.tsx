import { useState } from "react";

import { problemFrom, type Problem } from "../connection/problems";
import type { SyncState } from "./useSync";

/**
 * Columns that appeared in Notion after the mapping was saved and fit an unused field (issue
 * #12), for example "Parent Task" once its Task Tracker is shared with Habit Tracker. Shown on
 * Home and in Settings until the user reviews the mapping or dismisses the offer.
 */
export function MappingSuggestions({
  sync,
  onReviewMapping,
}: {
  sync: SyncState | null;
  onReviewMapping: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<{ id: string; problem: Problem } | null>(null);
  if (sync?.load.status !== "ready") return null;
  const suggestions = sync.load.sync.mapping_suggestions;
  if (suggestions.length === 0) return null;

  const dismiss = (propertyId: string) => {
    setBusy(propertyId);
    setProblem(null);
    sync
      .dismissSuggestion(propertyId)
      .catch((error: unknown) => {
        setProblem({ id: propertyId, problem: problemFrom(error) });
      })
      .finally(() => {
        setBusy(null);
      });
  };

  return (
    <>
      {suggestions.map((suggestion) => (
        <div
          key={suggestion.property_id}
          className="notice ok"
          role="status"
          aria-label={`New column for ${suggestion.field_label}`}
        >
          <strong>New column for {suggestion.field_label}</strong>
          <p>{suggestion.message}</p>
          {problem?.id === suggestion.property_id && (
            <p className="field-note error" role="alert">
              Couldn&apos;t dismiss it: {problem.problem.message}
            </p>
          )}
          <div className="actions">
            <button type="button" className="button primary" onClick={onReviewMapping}>
              Review column mapping
            </button>
            <button
              type="button"
              className="button"
              disabled={busy !== null}
              onClick={() => {
                dismiss(suggestion.property_id);
              }}
            >
              {busy === suggestion.property_id && <span className="spinner" aria-hidden="true" />}
              Dismiss
            </button>
          </div>
        </div>
      ))}
    </>
  );
}
