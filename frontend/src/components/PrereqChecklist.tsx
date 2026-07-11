import type { FoundationCourse } from "../types";

interface Props {
  courses: FoundationCourse[];
  completed: Set<string>;
  onToggle: (courseNum: string) => void;
}

// Step 2: tap-to-confirm the foundation courses already taken. Tapping (not
// typing) seeds the confirmed "completed" set (project context §3).
export function PrereqChecklist({ courses, completed, onToggle }: Props) {
  return (
    <div className="card">
      <h2>2 · Which of these have you taken?</h2>
      <p className="muted">
        Tick the foundation courses you've completed. This seeds your confirmed
        prerequisites.
      </p>
      {courses.length === 0 && <p className="muted">No foundation courses found.</p>}
      <ul className="checklist">
        {courses.map((c) => (
          <li key={c.course_num}>
            <label>
              <input
                type="checkbox"
                checked={completed.has(c.course_num)}
                onChange={() => onToggle(c.course_num)}
              />
              <span>
                <strong>{c.course_num}</strong> {c.title}{" "}
                <span className="muted">({c.units} units)</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
