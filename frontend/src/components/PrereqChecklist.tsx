import type { ChecklistGroup } from "../types";

interface Props {
  groups: ChecklistGroup[];
  completed: Set<string>;
  onToggle: (courseNum: string) => void;
}

// Step 2: tap-to-confirm the courses already taken. Tapping (not typing) seeds the
// confirmed "completed" set (project context §3), which feeds the classifier and
// the cascade re-solve on the next question. Scoped to core courses + common
// prerequisites and grouped under headers so it stays scannable.
export function PrereqChecklist({ groups, completed, onToggle }: Props) {
  const total = groups.reduce((n, g) => n + g.courses.length, 0);

  return (
    <div className="card">
      <h2>2 · Which of these have you taken?</h2>
      <p className="muted">
        Tick the core courses and common prerequisites you've completed. This seeds
        your confirmed prerequisites and cuts down on follow-up questions.
      </p>
      {total === 0 ? (
        <p className="muted">No checklist courses found.</p>
      ) : (
        <p className="checklist-progress" role="status">
          {completed.size} of {total} ticked
        </p>
      )}
      {groups.map((group) => (
        <div className="checklist-group" key={group.header}>
          <h3 className="checklist-header">{group.header}</h3>
          <ul className="checklist">
            {group.courses.map((c) => (
              <li key={c.course_num}>
                <label>
                  <input
                    type="checkbox"
                    checked={completed.has(c.course_num)}
                    onChange={() => onToggle(c.course_num)}
                  />
                  <span>
                    <strong>{c.course_num}</strong>
                    {c.title !== c.course_num && <> {c.title}</>}
                    {c.units != null && <span className="muted"> ({c.units} units)</span>}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
