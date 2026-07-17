import { useState } from "react";
import { chat, confirm as confirmApi, recommend } from "../api";
import type {
  ChatMessage,
  ConfirmationQuestion,
  ScheduleConstraints,
  ScheduleOut,
  StudentProfile,
} from "../types";
import { EMPTY_CONSTRAINTS } from "../types";
import { ChatThread } from "./ChatThread";
import { ConfirmationPanel } from "./ConfirmationPanel";
import { RationalePanel } from "./RationalePanel";
import { WeekGrid } from "./WeekGrid";

interface Props {
  profile: StudentProfile;
  // The checklist "completed" set; seeds the profile handed to the solver.
  completed: Set<string>;
}

// Part 3: the schedule workspace.
//
// The calendar sits beside a right-hand panel carrying (a) the rationale for the
// selected schedule — including the verifier's green checkmarks — and (b) the
// prerequisite confirmation controls. Below both is the chat, which can answer
// questions about the calendar or ask for changes to it.
//
// Every calendar on screen is the deterministic solver's output. A chat
// modification changes the *constraints* the solver is given and re-solves; the
// model never edits a schedule. Conversation state (history, constraints) is held
// here and echoed to the server, which keeps no session.
export function SchedulePanel({ profile, completed }: Props) {
  const [schedules, setSchedules] = useState<ScheduleOut[] | null>(null);
  const [questions, setQuestions] = useState<ConfirmationQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  const [selected, setSelected] = useState(0);
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [constraints, setConstraints] = useState<ScheduleConstraints>(EMPTY_CONSTRAINTS);
  const [lastKind, setLastKind] = useState<"question" | "modification" | null>(null);
  const [backend, setBackend] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The profile the solver sees carries the confirmed completed set.
  const solverProfile: StudentProfile = {
    ...profile,
    completed_courses: [...completed],
  };

  function applySchedules(next: {
    schedules: ScheduleOut[];
    confirmation_questions: ConfirmationQuestion[];
  }) {
    setSchedules(next.schedules);
    setQuestions(next.confirmation_questions);
    setSelected((s) => Math.min(s, Math.max(0, next.schedules.length - 1)));
  }

  async function build() {
    setBusy(true);
    setError(null);
    try {
      applySchedules(await recommend(solverProfile));
      // A fresh build starts from a clean slate.
      setAnswers({});
      setHistory([]);
      setConstraints(EMPTY_CONSTRAINTS);
      setLastKind(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not build schedules.");
    } finally {
      setBusy(false);
    }
  }

  // Answering a prereq toggle: record it, re-solve the cascade deterministically,
  // and swap the calendar in place. No LLM on this path, so it stays snappy.
  async function handleAnswer(prereq: string, taken: boolean) {
    const nextAnswers = { ...answers, [prereq]: taken };
    setAnswers(nextAnswers);
    setBusy(true);
    setError(null);
    try {
      applySchedules(await confirmApi(solverProfile, nextAnswers));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not re-solve.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSend(message: string) {
    setBusy(true);
    setError(null);
    try {
      const res = await chat({
        profile: solverProfile,
        message,
        answers,
        history,
        constraints,
        selected,
      });
      setHistory(res.history);
      setConstraints(res.constraints);
      setLastKind(res.kind);
      setBackend(res.llm_backend);
      // A question returns the calendar unchanged; a modification returns the
      // re-solved one. Either way this is the solver's output.
      applySchedules(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat request failed.");
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
          confirm prerequisites and refine by chatting.
        </p>
        {error && <p className="error">{error}</p>}
        <button type="button" onClick={build} disabled={busy}>
          {busy ? "Building…" : "Build schedule"}
        </button>
      </div>
    );
  }

  const active = schedules[selected] ?? null;
  const constraintSummary = [
    constraints.avoid_days.length > 0 && `no class ${constraints.avoid_days.join("/")}`,
    constraints.max_units != null && `≤ ${constraints.max_units} units`,
    constraints.no_class_before && `not before ${constraints.no_class_before.slice(0, 5)}`,
    constraints.no_class_after && `not after ${constraints.no_class_after.slice(0, 5)}`,
    constraints.exclude_courses.length > 0 && `without ${constraints.exclude_courses.join(", ")}`,
  ].filter(Boolean) as string[];

  return (
    <div className="card">
      <div className="panel-head">
        <h2>3 · Your schedule</h2>
        <button type="button" className="ghost" onClick={build} disabled={busy}>
          Reset
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {constraintSummary.length > 0 && (
        <div className="claims constraint-row">
          {constraintSummary.map((c) => (
            <span className="chip constraint" key={c} title="Applied by the solver">
              {c}
            </span>
          ))}
        </div>
      )}

      {schedules.length === 0 ? (
        <p className="muted">
          No conflict-free schedule fits the current answers and constraints. Try
          resetting, or ask for something less restrictive.
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
            {/* Rationale re-renders from `active`, so it follows the selection. */}
            <RationalePanel schedule={active} />
            <ConfirmationPanel
              questions={questions}
              answers={answers}
              onAnswer={handleAnswer}
              busy={busy}
            />
          </div>
        </div>
      )}

      <ChatThread
        history={history}
        onSend={handleSend}
        busy={busy}
        lastKind={lastKind}
        backend={backend}
      />
    </div>
  );
}
