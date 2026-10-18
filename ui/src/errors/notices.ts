import { useSyncExternalStore } from "react";

/** A non-fatal error shown as a dismissible banner at the top of the window. */
export interface ErrorNotice {
  key: number;
  title: string;
  message: string;
  errorId: string | null;
  detail: string | null;
}

export const MAX_NOTICES = 5;

type Listener = () => void;

let notices: readonly ErrorNotice[] = [];
let nextKey = 1;
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** Show a notice. The oldest is dropped once there are more than {@link MAX_NOTICES}. */
export function pushNotice(notice: Omit<ErrorNotice, "key">): number {
  const key = nextKey++;
  notices = [...notices, { ...notice, key }].slice(-MAX_NOTICES);
  emit();
  return key;
}

export function dismissNotice(key: number): void {
  notices = notices.filter((notice) => notice.key !== key);
  emit();
}

export function clearNoticesForTests(): void {
  notices = [];
  emit();
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): readonly ErrorNotice[] {
  return notices;
}

export function useNotices(): readonly ErrorNotice[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
