import type { Section } from "../types";

const DAYS = ["M", "T", "W", "R", "F"] as const;
const DAY_LABELS: Record<string, string> = {
  M: "Mon",
  T: "Tue",
  W: "Wed",
  R: "Thu",
  F: "Fri",
};
const DAY_NAMES: Record<string, string> = {
  M: "Monday",
  T: "Tuesday",
  W: "Wednesday",
  R: "Thursday",
  F: "Friday",
};

const START_MIN = 8 * 60; // 8:00
const END_MIN = 21 * 60; // 21:00
const PX_PER_MIN = 0.8; // 48px per hour

// Curated block palette: distinct hues, all with enough contrast for dark text.
// A course keeps its color across schedules (assignment is by course number).
const PALETTE = [
  { bg: "#dbe7fd", edge: "#3565c0" }, // blue
  { bg: "#d9f2e2", edge: "#1a7f4b" }, // green
  { bg: "#fde7d8", edge: "#b45f17" }, // orange
  { bg: "#eee3fa", edge: "#7444b8" }, // purple
  { bg: "#fbdfe4", edge: "#b8385a" }, // pink
  { bg: "#defafa", edge: "#0f7e86" }, // teal
  { bg: "#f7f0cf", edge: "#8a7413" }, // gold
  { bg: "#e8e8ec", edge: "#55555c" }, // slate
];

function toMinutes(hms: string): number {
  const [h, m] = hms.split(":");
  return Number(h) * 60 + Number(m);
}

function label(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}:${m.toString().padStart(2, "0")}`;
}

function colorFor(courseNum: string) {
  let hash = 0;
  for (const ch of courseNum) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

export function WeekGrid({ sections }: { sections: Section[] }) {
  const gridHeight = (END_MIN - START_MIN) * PX_PER_MIN;
  const hourLines: number[] = [];
  for (let m = START_MIN; m <= END_MIN; m += 60) hourLines.push(m);

  const legendCourses = [...new Map(sections.map((s) => [s.course_num, s])).values()];

  return (
    <div>
      <div className="weekgrid" role="group" aria-label="Weekly calendar of scheduled classes">
        <div className="weekgrid-axis" style={{ height: gridHeight }} aria-hidden="true">
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
                  aria-hidden="true"
                />
              ))}
              {sections
                .filter((s) => s.days.includes(day))
                .map((s) => {
                  const begin = toMinutes(s.begin);
                  const end = toMinutes(s.end);
                  const color = colorFor(s.course_num);
                  const detail = `${s.course_num} ${s.title}, ${DAY_NAMES[day]} ${label(
                    begin,
                  )} to ${label(end)}, ${s.location}, ${s.units} units`;
                  return (
                    <div
                      key={`${s.course_num}-${s.section_id}-${day}`}
                      className="weekgrid-block"
                      tabIndex={0}
                      aria-label={detail}
                      style={{
                        top: (begin - START_MIN) * PX_PER_MIN,
                        height: (end - begin) * PX_PER_MIN,
                        background: color.bg,
                        borderLeft: `3px solid ${color.edge}`,
                      }}
                    >
                      <strong>{s.course_num}</strong>
                      <span>
                        {label(begin)}–{label(end)}
                      </span>
                      {/* Hover/focus detail card; also read out via aria-label. */}
                      <div className="weekgrid-tip" role="presentation">
                        <strong>
                          {s.course_num} {s.title}
                        </strong>
                        <span>
                          {DAY_NAMES[day]} {label(begin)}–{label(end)}
                        </span>
                        <span>
                          {s.location} · section {s.section_id} · {s.units} units
                        </span>
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        ))}
      </div>

      {legendCourses.length > 0 && (
        <ul className="weekgrid-legend" aria-label="Course colors">
          {legendCourses.map((s) => {
            const color = colorFor(s.course_num);
            return (
              <li key={s.course_num}>
                <span
                  className="legend-swatch"
                  style={{ background: color.bg, borderColor: color.edge }}
                  aria-hidden="true"
                />
                <strong>{s.course_num}</strong> {s.title}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
