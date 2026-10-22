/** The computer's IANA time zone, e.g. "Asia/Kolkata": the dashboard's days follow it. */
export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/** 45 → "45 min", 90 → "1 h 30 min", 120 → "2 h", 0.4 → "0 min". */
export function formatDuration(minutes: number): string {
  const total = Math.round(minutes);
  if (total < 60) return `${String(total)} min`;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return rest === 0 ? `${String(hours)} h` : `${String(hours)} h ${String(rest)} min`;
}

/** Hours read better than minutes once a chart's tallest bar passes two hours. */
export function showHours(maxMinutes: number): boolean {
  return maxMinutes > 120;
}

export interface DateOptions {
  locale?: string | undefined;
}

function calendarDate(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, day ?? 1));
}

/** "Wed, 21 Oct 2026" — a calendar date, never shifted by a time zone. */
export function formatDay(iso: string, options: DateOptions = {}): string {
  return new Intl.DateTimeFormat(options.locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(calendarDate(iso));
}

/** "21 Oct" — for chart axes. */
export function formatShortDay(iso: string, options: DateOptions = {}): string {
  return new Intl.DateTimeFormat(options.locale, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(calendarDate(iso));
}

/** "21 Oct – 27 Oct 2026" style range. */
export function formatRange(first: string, last: string, options: DateOptions = {}): string {
  if (first === last) return formatDay(first, options);
  return `${formatShortDay(first, options)} – ${formatDay(last, options)}`;
}

/** A clock time in the dashboard's time zone, e.g. "9:00 AM". */
export function formatTime(utc: string, timeZone: string, options: DateOptions = {}): string {
  return new Intl.DateTimeFormat(options.locale, { timeStyle: "short", timeZone }).format(
    new Date(utc),
  );
}

/** A clock time with its date, e.g. "21 Oct, 11:00 PM". */
export function formatDateTime(utc: string, timeZone: string, options: DateOptions = {}): string {
  return new Intl.DateTimeFormat(options.locale, {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  }).format(new Date(utc));
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}
