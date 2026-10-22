import { describe, expect, it } from "vitest";

import type { Sample } from "../bridge/types";
import { formatMoment, formatSample } from "./format";

const india = { locale: "en-US", timeZone: "Asia/Kolkata" };

const range: Sample = {
  kind: "date",
  start: { utc: "2026-10-21T03:30:00.000Z", date: "2026-10-21", has_time: true },
  end: { utc: "2026-10-21T04:45:00.000Z", date: "2026-10-21", has_time: true },
};

describe("formatting sample values", () => {
  it("shows instants in local time", () => {
    const moment = { utc: "2026-10-17T12:11:00.000Z", date: "2026-10-17", has_time: true };
    expect(formatMoment(moment, india)).toBe("Oct 17, 2026, 5:41 PM");
    expect(formatMoment(moment, { locale: "en-US", timeZone: "America/New_York" })).toBe(
      "Oct 17, 2026, 8:11 AM",
    );
  });

  it("never moves a date without a time to another day", () => {
    const moment = { utc: null, date: "2026-10-17", has_time: false };
    expect(formatMoment(moment, { locale: "en-US", timeZone: "Pacific/Honolulu" })).toBe(
      "Oct 17, 2026",
    );
    expect(formatSample({ kind: "date", start: moment, end: null }, null, india)).toEqual({
      text: "Oct 17, 2026",
      noTime: true,
    });
  });

  it("shows a range on one day with the end's time only", () => {
    expect(formatSample(range, null, india)).toEqual({
      text: "Oct 21, 2026, 9:00 AM → 10:15 AM",
      noTime: false,
    });
  });

  it("shows a range across midnight with both dates", () => {
    const overnight: Sample = {
      kind: "date",
      start: { utc: "2026-10-21T17:00:00.000Z", date: "2026-10-21", has_time: true },
      end: { utc: "2026-10-21T19:00:00.000Z", date: "2026-10-22", has_time: true },
    };
    expect(formatSample(overnight, null, india)?.text).toBe(
      "Oct 21, 2026, 10:30 PM → Oct 22, 2026, 12:30 AM",
    );
  });

  it("shows only the part a field reads", () => {
    expect(formatSample(range, "start", india)?.text).toBe("Oct 21, 2026, 9:00 AM");
    expect(formatSample(range, "end", india)?.text).toBe("Oct 21, 2026, 10:15 AM");
  });

  it("has nothing to show for the end of a single date", () => {
    expect(formatSample({ ...range, end: null }, "end", india)).toBeNull();
  });

  it("passes text through", () => {
    expect(formatSample({ kind: "text", text: "Writing EVA resume" })).toEqual({
      text: "Writing EVA resume",
      noTime: false,
    });
  });
});
