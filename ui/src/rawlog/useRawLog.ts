import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { callPython } from "../bridge/client";
import type { RawLogFilters, RawLogPage, RawLogRow, SortSpec } from "../bridge/types";
import { problemFrom, type Problem } from "../connection/problems";
import { browserTimeZone } from "../dashboard/format";

/** Rows fetched per request; the table asks for the blocks it is showing. */
export const BLOCK_SIZE = 100;

export type RawLogLoad =
  | { status: "loading" }
  | { status: "error"; problem: Problem }
  | { status: "ready"; page: RawLogPage; refreshing: boolean };

interface Loaded {
  key: string;
  page: RawLogPage;
  blocks: Map<number, RawLogRow[]>;
}

/**
 * The raw log's rows for the current filters and sort, fetched a block at a time as the table
 * scrolls. A new query keeps the previous rows on screen (marked as refreshing) until its first
 * block arrives, so the table never flashes empty. `refreshKey` changes when a sync finishes.
 */
export function useRawLog(filters: RawLogFilters, sort: SortSpec | null, refreshKey: string) {
  const [attempt, setAttempt] = useState(0);
  const timeZone = browserTimeZone();
  const key = JSON.stringify([filters, sort, timeZone, refreshKey, attempt]);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failure, setFailure] = useState<{ key: string; problem: Problem } | null>(null);
  const [blockFailure, setBlockFailure] = useState<{ key: string; block: number } | null>(null);
  const pending = useRef(new Set<string>());
  // Answers to an older query are ignored.
  const latestKey = useRef(key);
  useEffect(() => {
    latestKey.current = key;
  }, [key]);

  const request = useCallback(
    (block: number) => ({
      time_zone: timeZone,
      filters,
      ...(sort ? { sort } : {}),
      offset: block * BLOCK_SIZE,
      limit: BLOCK_SIZE,
    }),
    [filters, sort, timeZone],
  );

  const fetchBlock = useCallback(
    (block: number, forKey: string) => {
      const id = `${forKey}#${String(block)}`;
      if (pending.current.has(id)) return;
      pending.current.add(id);
      callPython("get_raw_log", request(block))
        .then((page) => {
          if (forKey !== latestKey.current) return;
          setLoaded((previous) => {
            if (block === 0 || previous?.key !== forKey) {
              return { key: forKey, page, blocks: new Map([[block, page.rows]]) };
            }
            const blocks = new Map(previous.blocks);
            blocks.set(block, page.rows);
            return { ...previous, blocks };
          });
        })
        .catch((error: unknown) => {
          if (forKey !== latestKey.current) return;
          if (block === 0) setFailure({ key: forKey, problem: problemFrom(error) });
          else setBlockFailure({ key: forKey, block });
        })
        .finally(() => {
          pending.current.delete(id);
        });
    },
    [request],
  );

  useEffect(() => {
    fetchBlock(0, key);
  }, [fetchBlock, key]);

  const current = loaded?.key === key ? loaded : null;

  /** Make sure rows `first`..`last` (inclusive) are loaded or on their way. */
  const ensureRows = useCallback(
    (first: number, last: number) => {
      if (!current) return;
      const end = Math.min(last, current.page.matched - 1);
      for (let block = Math.floor(first / BLOCK_SIZE); block * BLOCK_SIZE <= end; block += 1) {
        if (!current.blocks.has(block) && blockFailure?.block !== block) fetchBlock(block, key);
      }
    },
    [current, blockFailure, fetchBlock, key],
  );

  const rowAt = useCallback(
    (index: number): RawLogRow | undefined => {
      const source = current ?? loaded;
      return source?.blocks.get(Math.floor(index / BLOCK_SIZE))?.[index % BLOCK_SIZE];
    },
    [current, loaded],
  );

  const retry = useCallback(() => {
    setFailure(null);
    setBlockFailure(null);
    setAttempt((n) => n + 1);
  }, []);

  const load: RawLogLoad = useMemo(() => {
    if (failure?.key === key) return { status: "error", problem: failure.problem };
    if (loaded) return { status: "ready", page: loaded.page, refreshing: loaded.key !== key };
    return { status: "loading" };
  }, [failure, key, loaded]);

  return {
    load,
    rowAt,
    ensureRows,
    retry,
    timeZone,
    /** A later block failed to load: the table offers to try again. */
    rowsFailed: blockFailure?.key === key,
    exportRequest: { time_zone: timeZone, filters, ...(sort ? { sort } : {}) },
  };
}
