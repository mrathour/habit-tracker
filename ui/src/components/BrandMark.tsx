/** The app icon (service/pages/icon.png) drawn as SVG: a rising week of daily totals. */
export function BrandMark() {
  const bars = [
    { x: 82, h: 96 },
    { x: 156, h: 152 },
    { x: 230, h: 120 },
    { x: 304, h: 208 },
    { x: 378, h: 272 },
  ];
  return (
    <svg className="brand-mark" viewBox="0 0 512 512" aria-hidden="true">
      <rect width="512" height="512" rx="104" fill="#2f6f5e" />
      {bars.map((bar) => (
        <g key={bar.x} fill="#ffffff">
          {/* Rounded top, square base. */}
          <rect x={bar.x} y={392 - bar.h} width="52" height={bar.h} rx="26" />
          <rect x={bar.x} y={366} width="52" height="26" />
        </g>
      ))}
    </svg>
  );
}
