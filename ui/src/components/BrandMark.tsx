/**
 * The app icon (packaging/icon/app-icon.svg) drawn inline: a clock whose ring fills like a
 * daily goal. Keep the two in step.
 */
export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 256 256" aria-hidden="true">
      <rect width="256" height="256" rx="56" fill="#2f6f5e" />
      <circle
        cx="128"
        cy="128"
        r="78"
        fill="none"
        stroke="#dcebe5"
        strokeOpacity=".28"
        strokeWidth="26"
      />
      <path
        d="M128 50 A78 78 0 1 1 50 128"
        fill="none"
        stroke="#dcebe5"
        strokeWidth="26"
        strokeLinecap="round"
      />
      <path
        d="M128 128 L128 88 M128 128 L156 146"
        fill="none"
        stroke="#f0c36b"
        strokeWidth="16"
        strokeLinecap="round"
      />
      <circle cx="128" cy="128" r="12" fill="#f0c36b" />
    </svg>
  );
}
