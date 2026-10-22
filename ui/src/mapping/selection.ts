import type { FieldKey, FieldRef, FieldReview, MappingReview } from "../bridge/types";

export type Selections = Record<FieldKey, FieldRef | null>;

/** The value of a field's <select>: "" means nothing chosen yet. */
export const UNCHOSEN = "";
export const NOT_USED = "__not_used__";

export function encodeRef(ref: FieldRef | null): string {
  if (!ref) return UNCHOSEN;
  return ref.part ? `${ref.part}|${ref.property_id}` : `|${ref.property_id}`;
}

export function decodeRef(value: string): FieldRef | null {
  if (value === UNCHOSEN || value === NOT_USED) return null;
  const bar = value.indexOf("|");
  const part = value.slice(0, bar);
  const propertyId = value.slice(bar + 1);
  return part === "start" || part === "end"
    ? { property_id: propertyId, part }
    : { property_id: propertyId };
}

export function initialSelections(review: MappingReview): Selections {
  return Object.fromEntries(review.fields.map((f) => [f.key, f.selection])) as Selections;
}

export function sameRef(a: FieldRef | null, b: FieldRef | null): boolean {
  return a?.property_id === b?.property_id && (a?.part ?? null) === (b?.part ?? null);
}

/** The end of a date range shares its Start column; every other mapping uses a column alone. */
export function isRangeEnd(key: FieldKey, ref: FieldRef | null): boolean {
  return key === "end" && ref?.part === "end";
}

/** Which field uses each column, so other fields can show it as taken. */
export function columnUsers(selections: Selections): Map<string, FieldKey> {
  const users = new Map<string, FieldKey>();
  for (const [key, ref] of Object.entries(selections) as [FieldKey, FieldRef | null][]) {
    if (ref && !isRangeEnd(key, ref)) users.set(ref.property_id, key);
  }
  return users;
}

/**
 * Change one field. When Start moves to another column and End was "the end of the date range
 * in the Start column", End follows Start: the range end belongs to whichever column holds the
 * start.
 */
export function choose(selections: Selections, key: FieldKey, ref: FieldRef | null): Selections {
  const next = { ...selections, [key]: ref };
  if (key === "start" && isRangeEnd("end", selections.end)) {
    next.end = ref ? { property_id: ref.property_id, part: "end" } : null;
  }
  return next;
}

/** Fields that still need a decision, each with the sentence the screen shows for it. */
export function blockingReasons(
  review: MappingReview,
  selections: Selections,
  decided: ReadonlySet<FieldKey>,
): { key: FieldKey; text: string }[] {
  const reasons: { key: FieldKey; text: string }[] = [];
  for (const field of review.fields) {
    const ref = selections[field.key];
    if (field.required && !ref) {
      reasons.push({
        key: field.key,
        text: field.missing_help ?? `Choose a ${field.needs} column for ${field.label}.`,
      });
    } else if (!field.required && field.status === "choose" && !decided.has(field.key)) {
      reasons.push({
        key: field.key,
        text: `Choose a column for ${field.label}, or set it to Not used.`,
      });
    }
  }
  return reasons;
}

export function isDirty(
  review: MappingReview,
  selections: Selections,
  extra: ReadonlySet<string>,
): boolean {
  const fieldsChanged = review.fields.some((f) => !sameRef(f.selection, selections[f.key]));
  const saved = new Set(review.extra);
  return fieldsChanged || saved.size !== extra.size || [...extra].some((id) => !saved.has(id));
}

/** Options the field's <select> may show: a range end only for the current Start column. */
export function visibleOptions(field: FieldReview, selections: Selections) {
  if (field.key !== "end") return field.options;
  const startId = selections.start?.property_id;
  return field.options.filter((o) => o.part !== "end" || o.property_id === startId);
}
