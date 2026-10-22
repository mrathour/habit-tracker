/**
 * A week of work sessions on a 24-hour axis: the kind of picture Habit Tracker makes from a
 * Notion work log. Decorative on the Connect screen, so it is hidden from screen readers.
 */

interface Session {
  start: number; // hours from midnight
  end: number;
}

const WEEK: { day: string; sessions: Session[] }[] = [
  {
    day: "Mon",
    sessions: [
      { start: 9.25, end: 11.5 },
      { start: 13, end: 15.75 },
      { start: 21, end: 22.25 },
    ],
  },
  {
    day: "Tue",
    sessions: [
      { start: 8.75, end: 12.25 },
      { start: 14.5, end: 17 },
    ],
  },
  {
    day: "Wed",
    sessions: [
      { start: 10, end: 11 },
      { start: 16.25, end: 18.5 },
    ],
  },
  {
    day: "Thu",
    sessions: [
      { start: 9, end: 12.75 },
      { start: 13.5, end: 16 },
      { start: 20.5, end: 23.75 },
    ],
  },
  {
    day: "Fri",
    sessions: [
      { start: 9.5, end: 13 },
      { start: 15, end: 16.25 },
    ],
  },
  { day: "Sat", sessions: [{ start: 11, end: 12.5 }] },
  { day: "Sun", sessions: [{ start: 22.5, end: 24 }] },
];

const LEFT = 44;
const RIGHT = 64;
const WIDTH = 560;
const ROW = 34;
const TRACK = 14;
const TOP = 22;
const SPAN = WIDTH - LEFT - RIGHT;

function x(hour: number): number {
  return LEFT + (hour / 24) * SPAN;
}

function total(sessions: Session[]): string {
  const minutes = Math.round(sessions.reduce((sum, s) => sum + (s.end - s.start) * 60, 0));
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

export function TimeStrip() {
  const height = TOP + WEEK.length * ROW + 6;
  return (
    <svg
      className="timestrip"
      viewBox={`0 0 ${WIDTH} ${height}`}
      role="presentation"
      aria-hidden="true"
      focusable="false"
    >
      {[0, 6, 12, 18, 24].map((hour) => (
        <g key={hour}>
          <line className="gridline" x1={x(hour)} x2={x(hour)} y1={TOP - 6} y2={height - 6} />
          <text className="hour" x={x(hour)} y={12} textAnchor="middle">
            {String(hour).padStart(2, "0")}:00
          </text>
        </g>
      ))}
      {WEEK.map((row, index) => {
        const y = TOP + index * ROW + (ROW - TRACK) / 2;
        return (
          <g key={row.day}>
            <text className="day" x={0} y={y + TRACK - 2}>
              {row.day}
            </text>
            <rect className="track" x={LEFT} y={y} width={SPAN} height={TRACK} rx={3} />
            {row.sessions.map((s) => (
              <rect
                key={s.start}
                className="session"
                x={x(s.start)}
                y={y}
                width={Math.max(x(s.end) - x(s.start), 3)}
                height={TRACK}
                rx={3}
              />
            ))}
            <text className="total" x={WIDTH} y={y + TRACK - 2} textAnchor="end">
              {total(row.sessions)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
