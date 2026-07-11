import type { Section } from "../types";

const DAYS = ["M", "T", "W", "R", "F"] as const;
const DAY_LABELS: Record<string, string> = {
  M: "Mon",
  T: "Tue",
  W: "Wed",
  R: "Thu",
  F: "Fri",
};

const START_MIN = 8 * 60; // 8:00
const END_MIN = 21 * 60; // 21:00
const PX_PER_MIN = 0.8; // 48px per hour

function toMinutes(hms: string): number {
  const [h, m] = hms.split(":");
  return Number(h) * 60 + Number(m);
}

function label(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}:${m.toString().padStart(2, "0")}`;
}

// Stable pastel color per course so the same course reads the same across schedules.
function colorFor(courseNum: string): string {
  let hash = 0;
  for (const ch of courseNum) hash = (hash * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${hash}, 55%, 82%)`;
}

export function WeekGrid({ sections }: { sections: Section[] }) {
  const gridHeight = (END_MIN - START_MIN) * PX_PER_MIN;
  const hourLines: number[] = [];
  for (let m = START_MIN; m <= END_MIN; m += 60) hourLines.push(m);

  return (
    <div className="weekgrid">
      <div className="weekgrid-axis" style={{ height: gridHeight }}>
        {hourLines.map((m) => (
          <div
            key={m}
            className="weekgrid-hour-label"
            style={{ top: (m - START_MIN) * PX_PER_MIN }}
          >
            {label(m)}
          </div>
        ))}
      </div>
      {DAYS.map((day) => (
        <div className="weekgrid-day" key={day}>
          <div className="weekgrid-day-header">{DAY_LABELS[day]}</div>
          <div className="weekgrid-day-body" style={{ height: gridHeight }}>
            {hourLines.map((m) => (
              <div
                key={m}
                className="weekgrid-line"
                style={{ top: (m - START_MIN) * PX_PER_MIN }}
              />
            ))}
            {sections
              .filter((s) => s.days.includes(day))
              .map((s) => {
                const begin = toMinutes(s.begin);
                const end = toMinutes(s.end);
                return (
                  <div
                    key={`${s.course_num}-${s.section_id}-${day}`}
                    className="weekgrid-block"
                    style={{
                      top: (begin - START_MIN) * PX_PER_MIN,
                      height: (end - begin) * PX_PER_MIN,
                      background: colorFor(s.course_num),
                    }}
                    title={`${s.course_num} ${s.title} — ${s.location}`}
                  >
                    <strong>{s.course_num}</strong>
                    <span>
                      {label(begin)}–{label(end)}
                    </span>
                  </div>
                );
              })}
          </div>
        </div>
      ))}
    </div>
  );
}
