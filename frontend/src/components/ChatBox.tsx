import { useState } from "react";
import type { AskResponse, AskResult } from "../types";
import { WeekGrid } from "./WeekGrid";

interface Props {
  onAsk: (question: string) => Promise<AskResponse>;
}

function claimText(claim: AskResult["verified_claims"][number]): string {
  switch (claim.type) {
    case "total_units":
      return `${claim.value} total units`;
    case "no_class_on":
      return `No class on ${claim.day}`;
    case "includes_course":
      return `Includes ${claim.course_num}`;
    case "no_conflicts":
      return "No time conflicts";
    default:
      return claim.type;
  }
}

function ResultCard({ result }: { result: AskResult }) {
  return (
    <div className="result">
      <div className="result-head">
        <span className="badge">Option {result.fit_rank ?? "?"}</span>
        <span className="muted">
          {result.total_units} units · ~{result.total_workload_hours} hrs/wk
        </span>
      </div>
      {result.explanation && <p className="explanation">{result.explanation}</p>}

      <WeekGrid sections={result.sections} />

      {result.verified_claims.length > 0 && (
        <div className="claims">
          {result.verified_claims.map((c, i) => (
            <span className="chip verified" key={i}>
              ✓ {claimText(c)}
            </span>
          ))}
        </div>
      )}

      {result.confirmation_questions.length > 0 && (
        <div className="confirm">
          {result.confirmation_questions.map((q) => (
            <p key={q.course_num} className="confirm-q">
              ⚠ {q.question}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// Step 3: conversational recommendation. Sends the question to /ask and renders
// the verified, explained schedules.
export function ChatBox({ onAsk }: Props) {
  const [question, setQuestion] = useState(
    "Which of these schedules best fits my interests?",
  );
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResponse(await onAsk(question));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2>3 · Ask for a schedule</h2>
      <form className="chat-form" onSubmit={submit}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Which schedule has no Friday classes?"
        />
        <button type="submit" disabled={busy}>
          {busy ? "Thinking…" : "Ask"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {response && (
        <>
          <p className="muted route-line">
            Routed as <strong>{response.route}</strong> · answered by{" "}
            <strong>{response.llm_backend}</strong>
          </p>
          {response.results.length === 0 && (
            <p className="muted">No valid schedules found for that profile.</p>
          )}
          {response.results.map((r, i) => (
            <ResultCard result={r} key={i} />
          ))}
        </>
      )}
    </div>
  );
}
