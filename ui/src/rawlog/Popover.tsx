import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/**
 * A small panel opened from a button: placed under it (fixed, so a scrolling table never clips
 * it), focus moves in, and Escape, a click outside or scrolling closes it and returns focus.
 */
export function Popover({
  anchor,
  label,
  onClose,
  children,
  className = "",
}: {
  anchor: HTMLElement;
  label: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  // The latest onClose, so the listeners below are set up once per opening.
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  useLayoutEffect(() => {
    const box = anchor.getBoundingClientRect();
    const width = ref.current?.offsetWidth ?? 0;
    const left = Math.max(8, Math.min(box.left, window.innerWidth - width - 8));
    setPlace({ top: box.bottom + 4, left });
  }, [anchor]);

  useEffect(() => {
    ref.current
      ?.querySelector<HTMLElement>("input, button, select, [href], [tabindex]:not([tabindex='-1'])")
      ?.focus();
    const onPointer = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!ref.current?.contains(target) && !anchor.contains(target)) close.current();
    };
    const onScroll = (event: Event) => {
      if (!ref.current?.contains(event.target as Node)) close.current();
    };
    document.addEventListener("mousedown", onPointer);
    window.addEventListener("scroll", onScroll, true);
    const panel = ref.current;
    return () => {
      document.removeEventListener("mousedown", onPointer);
      window.removeEventListener("scroll", onScroll, true);
      // Return focus unless the user has already moved it somewhere else.
      const active = document.activeElement;
      if (!active || active === document.body || panel?.contains(active)) anchor.focus();
    };
  }, [anchor]);

  return (
    <div
      ref={ref}
      className={`popover ${className}`}
      role="dialog"
      aria-label={label}
      style={place ? { top: place.top, left: place.left } : { visibility: "hidden" }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      {children}
    </div>
  );
}
