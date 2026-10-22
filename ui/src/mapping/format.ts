import type { DatePart, Sample, SampleMoment } from "../bridge/types";

/** Locale and time zone for display. Undefined means the computer's own (tests pin them). */
export interface DisplayOptions {
  locale?: string | undefined;
  timeZone?: string | undefined;
}

export interface FormattedSample {
  text: string;
  /** A date without a time: validation will flag it as Missing time (PLAN.md 5). */
  noTime: boolean;
}

function dateOnly(moment: SampleMoment, options: DisplayOptions): string {
  // A date without a time is a calendar date, not an instant: format it in UTC so no time zone
  // can move it to the day before.
  const [year, month, day] = moment.date.split("-").map(Number);
  const when = new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, day ?? 1));
  return new Intl.DateTimeFormat(options.locale, {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(when);
}

/** One end of a Notion date, in local time ("Oct 17, 2026, 5:41 PM"). */
export function formatMoment(moment: SampleMoment, options: DisplayOptions = {}): string {
  if (!moment.utc) return dateOnly(moment, options);
  return new Intl.DateTimeFormat(options.locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: options.timeZone,
  }).format(new Date(moment.utc));
}

function formatTime(moment: SampleMoment, options: DisplayOptions): string {
  return new Intl.DateTimeFormat(options.locale, {
    timeStyle: "short",
    timeZone: options.timeZone,
  }).format(new Date(moment.utc ?? 0));
}

function sameLocalDay(a: SampleMoment, b: SampleMoment, options: DisplayOptions): boolean {
  if (!a.utc || !b.utc) return a.date === b.date;
  const day = new Intl.DateTimeFormat("en-CA", { dateStyle: "short", timeZone: options.timeZone });
  return day.format(new Date(a.utc)) === day.format(new Date(b.utc));
}

/**
 * A sample value as the review screen shows it.
 *
 * `part` picks one end of a date: a field mapped to the end of a range shows only the end,
 * exactly what the app will read. Without `part`, ranges show "start → end".
 */
export function formatSample(
  sample: Sample,
  part?: DatePart | null,
  options: DisplayOptions = {},
): FormattedSample | null {
  if (sample.kind === "text") return { text: sample.text, noTime: false };
  if (part === "end") {
    if (!sample.end) return null;
    return { text: formatMoment(sample.end, options), noTime: !sample.end.has_time };
  }
  const start = formatMoment(sample.start, options);
  if (part === "start" || !sample.end) {
    return { text: start, noTime: !sample.start.has_time };
  }
  const end =
    sample.start.has_time && sample.end.has_time && sameLocalDay(sample.start, sample.end, options)
      ? formatTime(sample.end, options)
      : formatMoment(sample.end, options);
  return { text: `${start} → ${end}`, noTime: !sample.start.has_time || !sample.end.has_time };
}
