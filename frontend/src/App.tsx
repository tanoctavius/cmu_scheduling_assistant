import { useState } from "react";
import { ask, getSurvey } from "./api";
import { ChatBox } from "./components/ChatBox";
import { PrereqChecklist } from "./components/PrereqChecklist";
import { SurveyForm } from "./components/SurveyForm";
import type { AskResponse, FoundationCourse, StudentProfile } from "./types";

export default function App() {
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [foundation, setFoundation] = useState<FoundationCourse[]>([]);
  const [completed, setCompleted] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSurvey(p: StudentProfile) {
    setBusy(true);
    setError(null);
    try {
      const survey = await getSurvey(p);
      setProfile(p);
      setFoundation(survey.foundation_courses);
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

  // The profile handed to /ask carries the confirmed completed set.
  function handleAsk(question: string): Promise<AskResponse> {
    if (!profile) return Promise.reject(new Error("No profile yet."));
    return ask({ ...profile, completed_courses: [...completed] }, question);
  }

  return (
    <div className="page">
      <header>
        <h1>CMU Scheduler</h1>
        <p className="muted">
          Conflict-free, requirement-satisfying schedules — explained and verified.
        </p>
      </header>

      {error && <p className="error">{error}</p>}

      {!profile ? (
        <SurveyForm onSubmit={handleSurvey} busy={busy} />
      ) : (
        <div className="columns">
          <div className="col-left">
            <PrereqChecklist
              courses={foundation}
              completed={completed}
              onToggle={toggle}
            />
          </div>
          <div className="col-right">
            <ChatBox onAsk={handleAsk} />
          </div>
        </div>
      )}
    </div>
  );
}
