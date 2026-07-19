import { useState } from "react";
import { getSurvey } from "./api";
import { PrereqChecklist } from "./components/PrereqChecklist";
import { SchedulePanel } from "./components/SchedulePanel";
import { SurveyForm } from "./components/SurveyForm";
import type { ChecklistGroup, StudentProfile } from "./types";

// The three-part flow, in order: survey → prereq checklist → schedule workspace.
// `Stepper` renders where the student is; the data flow underneath is unchanged.
const STEPS = ["Survey", "Prerequisites", "Schedule"] as const;

function Stepper({ current, done }: { current: number; done: boolean[] }) {
  return (
    <ol className="stepper" aria-label="Progress">
      {STEPS.map((label, i) => {
        const state = done[i] ? "done" : i === current ? "current" : "todo";
        return (
          <li
            key={label}
            className={`step ${state}`}
            aria-current={i === current ? "step" : undefined}
          >
            <span className="step-dot" aria-hidden="true">
              {done[i] ? "✓" : i + 1}
            </span>
            <span className="step-label">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

export default function App() {
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [checklist, setChecklist] = useState<ChecklistGroup[]>([]);
  const [completed, setCompleted] = useState<Set<string>>(new Set());
  const [built, setBuilt] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSurvey(p: StudentProfile) {
    setBusy(true);
    setError(null);
    try {
      const survey = await getSurvey(p);
      setProfile(p);
      setChecklist(survey.checklist);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach the backend.");
    } finally {
      setBusy(false);
    }
  }

  function toggle(courseNum: string) {
    setCompleted((prev) => {
      const next = new Set(prev);
      if (next.has(courseNum)) next.delete(courseNum);
      else next.add(courseNum);
      return next;
    });
  }

  function restart() {
    setProfile(null);
    setChecklist([]);
    setCompleted(new Set());
    setBuilt(false);
    setError(null);
  }

  const current = !profile ? 0 : built ? 2 : 1;
  const done = [profile !== null, profile !== null && built, false];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>CMU Scheduler</h1>
          <p className="muted">
            Conflict-free, requirement-satisfying schedules — explained and verified.
          </p>
        </div>
        <Stepper current={current} done={done} />
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!profile ? (
        <SurveyForm onSubmit={handleSurvey} busy={busy} />
      ) : (
        <div className="columns">
          <div className="col-left">
            <PrereqChecklist
              groups={checklist}
              completed={completed}
              onToggle={toggle}
            />
            <button type="button" className="ghost restart" onClick={restart}>
              ← Change survey answers
            </button>
          </div>
          <div className="col-right">
            <SchedulePanel
              profile={profile}
              completed={completed}
              onBuiltChange={setBuilt}
            />
          </div>
        </div>
      )}
    </div>
  );
}
