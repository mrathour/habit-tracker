import type { ExtraCell, MomentCell } from "../bridge/types";

export interface FormatOptions {
  locale?: string | undefined;
}

/** "21 Oct 2026, 9:00 AM" in the raw log's time zone. */
export function formatStamp(utc: string, timeZone: string, options: FormatOptions = {}): string {
  return new Intl.DateTimeFormat(options.locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  }).format(new Date(utc));
}

/** A calendar date ("2026-10-30"), never shifted by a time zone: "30 Oct 2026". */
export function formatCalendarDate(iso: string, options: FormatOptions = {}): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat(options.locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, day ?? 1)));
}

/**
 * Minutes as validation words them ("Logged 148 min, but Start → End is 123 min"), so a
 * Duration and a Logged minutes cell can be compared at a glance: 123 → "123 min", 2.5 →
 * "2.5 min".
 */
export function formatMinutes(minutes: number): string {
  const rounded = Math.round(minutes * 10) / 10;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return `${text} min`;
}

function formatMoment(moment: MomentCell, timeZone: string, options: FormatOptions): string {
  if (moment.has_time && moment.utc) return formatStamp(moment.utc, timeZone, options);
  return formatCalendarDate(moment.date, options);
}

/** An extra field's cell as text: dates in local time, everything else as Python sent it. */
export function extraText(
  cell: ExtraCell | null | undefined,
  timeZone: string,
  options: FormatOptions = {},
): string | null {
  if (!cell) return null;
  if (cell.start) {
    const start = formatMoment(cell.start, timeZone, options);
    return cell.end ? `${start} → ${formatMoment(cell.end, timeZone, options)}` : start;
  }
  return cell.text;
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}
