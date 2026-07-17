import { useState } from "react";
import { confirm as confirmApi, recommend } from "../api";
import type {
  ConfirmationQuestion,
  ScheduleOut,
  StudentProfile,
} from "../types";
import { ConfirmationPanel } from "./ConfirmationPanel";
import { WeekGrid } from "./WeekGrid";

interface Props {
  profile: StudentProfile;
  // The checklist "completed" set; seeds the profile handed to the solver.
  completed: Set<string>;
}

// The prerequisite-confirmation workspace: the week-grid calendar with the
// interactive confirmation panel beside it. Both are driven by the deterministic
// endpoints — /recommend to seed, /confirm on every answer — so confirmations go
// straight to the classifier/solver and NEVER through the LLM. Answers re-solve
// the cascade and update the calendar in place, with a loading overlay meanwhile.
export function SchedulePanel({ profile, completed }: Props) {
  const [schedules, setSchedules] = useState<ScheduleOut[] | null>(null);
  const [questions, setQuestions] = useState<ConfirmationQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The profile the solver sees carries the confirmed completed set.
  const solverProfile: StudentProfile = {
    ...profile,
    completed_courses: [...completed],
  };

  function applyResult(next: {
    schedules: ScheduleOut[];
    confirmation_questions: ConfirmationQuestion[];
  }) {
    setSchedules(next.schedules);
    setQuestions(next.confirmation_questions);
    // Keep the selected calendar in range as the schedule set changes.
    setSelected((s) => Math.min(s, Math.max(0, next.schedules.length - 1)));
  }

  async function build() {
    setBusy(true);
    setError(null);
    try {
      applyResult(await recommend(solverProfile));
      // A fresh build starts from a clean slate of answers.
      setAnswers({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not build schedules.");
    } finally {
      setBusy(false);
    }
  }

  // Answering a single prereq toggle: record it, then re-solve the whole cascade
  // deterministically and swap the calendar in place.
  async function handleAnswer(prereq: string, taken: boolean) {
    const nextAnswers = { ...answers, [prereq]: taken };
    setAnswers(nextAnswers);
    setBusy(true);
    setError(null);
    try {
      applyResult(await confirmApi(solverProfile, nextAnswers));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not re-solve.");
    } finally {
      setBusy(false);
    }
  }

  if (schedules === null) {
    return (
      <div className="card">
        <h2>3 · Build your schedule</h2>
        <p className="muted">
          Generate conflict-free schedules from the courses you've ticked, then
          confirm prerequisites to unlock more.
        </p>
        {error && <p className="error">{error}</p>}
        <button type="button" onClick={build} disabled={busy}>
          {busy ? "Building…" : "Build schedule"}
        </button>
      </div>
    );
  }

  const active = schedules[selected];

  return (
    <div className="card">
      <div className="panel-head">
        <h2>3 · Schedule &amp; prerequisites</h2>
        <button type="button" className="ghost" onClick={build} disabled={busy}>
          Rebuild
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {schedules.length === 0 ? (
        <p className="muted">
          No conflict-free schedule fits those answers. Try changing a prerequisite
          answer above, or rebuild.
        </p>
      ) : (
        <div className="workspace">
          <div className="workspace-calendar">
            {schedules.length > 1 && (
              <div className="option-tabs" role="tablist">
                {schedules.map((_, i) => (
                  <button
                    key={i}
                    type="button"
                    role="tab"
                    aria-selected={i === selected}
                    className={`option-tab ${i === selected ? "on" : ""}`}
                    onClick={() => setSelected(i)}
                    disabled={busy}
                  >
                    Option {i + 1}
                  </button>
                ))}
              </div>
            )}
            <div className="calendar-wrap">
              {active && <WeekGrid sections={active.sections} />}
              {busy && (
                <div className="calendar-loading" role="status">
                  Re-solving…
                </div>
              )}
            </div>
            {active && (
              <p className="muted">
                {active.total_units} units · ~{active.total_workload_hours} hrs/wk
              </p>
            )}
          </div>

          <div className="workspace-panel">
            <ConfirmationPanel
              questions={questions}
              answers={answers}
              onAnswer={handleAnswer}
              busy={busy}
            />
          </div>
        </div>
      )}
    </div>
  );
}
