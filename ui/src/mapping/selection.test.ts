import { describe, expect, it } from "vitest";

import { reviews } from "../test/fakeBridge";
import {
  blockingReasons,
  choose,
  columnUsers,
  decodeRef,
  encodeRef,
  initialSelections,
  isDirty,
  NOT_USED,
  UNCHOSEN,
  visibleOptions,
} from "./selection";

describe("select values", () => {
  it("round-trip every kind of reference", () => {
    for (const ref of [
      { property_id: "%3DjVp", part: "start" as const },
      { property_id: "s%3A1", part: "end" as const },
      { property_id: "title" },
      { property_id: "a|b" },
    ]) {
      expect(decodeRef(encodeRef(ref))).toEqual(ref);
    }
    expect(decodeRef(UNCHOSEN)).toBeNull();
    expect(decodeRef(NOT_USED)).toBeNull();
    expect(encodeRef(null)).toBe(UNCHOSEN);
  });
});

describe("choosing columns", () => {
  it("starts from the review's selections", () => {
    const selections = initialSelections(reviews.workLog);
    expect(selections.task_name).toEqual({ property_id: "title" });
    expect(blockingReasons(reviews.workLog, selections, new Set())).toEqual([]);
    expect(isDirty(reviews.workLog, selections, new Set())).toBe(false);
  });

  it("marks columns used by other fields", () => {
    const users = columnUsers(initialSelections(reviews.workLog));
    expect(users.get("title")).toBe("task_name");
    expect(users.get("ZCx%3F")).toBe("logged_minutes");
  });

  it("does not count the range end as a second use of the Start column", () => {
    const users = columnUsers(initialSelections(reviews.range));
    expect(users.get("s%3A1")).toBe("start");
  });

  it("keeps a range end with its Start column when Start moves", () => {
    const selections = initialSelections(reviews.range);
    const moved = choose(selections, "start", { property_id: "other", part: "start" });
    expect(moved.end).toEqual({ property_id: "other", part: "end" });
  });

  it("leaves an ordinary End alone when Start moves", () => {
    const selections = initialSelections(reviews.workLog);
    const moved = choose(selections, "start", { property_id: "other", part: "start" });
    expect(moved.end).toEqual(selections.end);
  });

  it("offers the range end only for the current Start column", () => {
    const review = reviews.workLog;
    const end = review.fields.find((f) => f.key === "end");
    if (!end) throw new Error("no end field");
    const labels = visibleOptions(end, initialSelections(review)).map((o) => o.label);
    expect(labels).toEqual(["Start Time", "End Time", "End of the date range in “Start Time”"]);
  });

  it("notices changes to fields and additional fields", () => {
    const selections = initialSelections(reviews.workLog);
    expect(isDirty(reviews.workLog, { ...selections, display_id: null }, new Set())).toBe(true);
    expect(isDirty(reviews.workLog, selections, new Set(["mood"]))).toBe(true);
  });
});

describe("what blocks saving", () => {
  it("explains a missing end-time column exactly", () => {
    const reasons = blockingReasons(reviews.noEnd, initialSelections(reviews.noEnd), new Set());
    expect(reasons).toHaveLength(1);
    expect(reasons[0]?.key).toBe("end");
    expect(reasons[0]?.text).toMatch(/^Your database needs a second Date column/);
  });

  it("asks for every field that was too close to call", () => {
    const review = reviews.ambiguous;
    const reasons = blockingReasons(review, initialSelections(review), new Set());
    expect(reasons.map((r) => r.key)).toEqual(["start", "end", "parent_task"]);
    expect(reasons[2]?.text).toBe("Choose a column for Parent task link, or set it to Not used.");
  });

  it("accepts Not used as an answer for an optional field", () => {
    const review = reviews.ambiguous;
    const selections = {
      ...initialSelections(review),
      start: { property_id: "d1", part: "start" as const },
      end: { property_id: "d2", part: "start" as const },
    };
    expect(blockingReasons(review, selections, new Set(["start", "end", "parent_task"]))).toEqual(
      [],
    );
  });
});
