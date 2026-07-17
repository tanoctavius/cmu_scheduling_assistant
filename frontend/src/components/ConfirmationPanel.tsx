import type { ConfirmationQuestion } from "../types";

interface Props {
  questions: ConfirmationQuestion[];
  // prereq course number -> the student's answer (undefined = not yet answered).
  answers: Record<string, boolean>;
  // Fired the instant a Yes/No is picked; the parent calls /confirm and re-solves.
  onAnswer: (prereq: string, taken: boolean) => void;
  busy: boolean;
}

function requiresLine(courseNum: string, missing: string[]): string {
  if (missing.length === 0) return `${courseNum} has unconfirmed prerequisites`;
  return `${courseNum} requires ${missing.join(" and ")}`;
}

// Interactive prerequisite confirmation, lifted out of the chat flow and parked
// next to the calendar. Each unconfirmed recommended course lists its missing
// prereqs with Yes/No toggles; answering immediately drives the deterministic
// cascade re-solve (see SchedulePanel) — it never touches the LLM.
export function ConfirmationPanel({ questions, answers, onAnswer, busy }: Props) {
  return (
    <div className="confirm-panel">
      <h3>Confirm prerequisites</h3>
      {questions.length === 0 ? (
        <p className="muted">
          No prerequisites to confirm — every recommended course is eligible.
        </p>
      ) : (
        <>
          <p className="muted">
            Answer these to unlock dependent courses. The calendar updates as you go.
          </p>
          <ul className="confirm-list">
            {questions.map((q) => (
              <li key={q.course_num} className="confirm-control">
                <div className="confirm-course">
                  {requiresLine(q.course_num, q.missing_prereqs)}
                </div>
                <div className="confirm-prereqs">
                  {q.missing_prereqs.map((prereq) => {
                    const answer = answers[prereq];
                    return (
                      <div className="confirm-prereq" key={prereq}>
                        <span className="confirm-prereq-num">{prereq}</span>
                        <div className="toggle-group" role="group" aria-label={prereq}>
                          <button
                            type="button"
                            className={`toggle ${answer === true ? "on yes" : ""}`}
                            aria-pressed={answer === true}
                            disabled={busy}
                            onClick={() => onAnswer(prereq, true)}
                          >
                            Yes
                          </button>
                          <button
                            type="button"
                            className={`toggle ${answer === false ? "on no" : ""}`}
                            aria-pressed={answer === false}
                            disabled={busy}
                            onClick={() => onAnswer(prereq, false)}
                          >
                            No
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
