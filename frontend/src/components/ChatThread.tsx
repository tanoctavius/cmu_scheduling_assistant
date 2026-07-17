import { useState } from "react";
import type { ChatMessage } from "../types";

interface Props {
  history: ChatMessage[];
  onSend: (message: string) => void;
  busy: boolean;
  // Set when the last turn re-solved the calendar, so the thread can say so.
  lastKind: "question" | "modification" | null;
  backend: string | null;
}

const EXAMPLES = [
  "What's my workload?",
  "Swap the Friday class",
  "Make it lighter",
  "Prioritize morning classes",
];

// The conversational half of Part 3. Asks questions about the calendar and
// requests changes to it; the answer and any new calendar come from the backend,
// where the solver — not the model — does the scheduling.
export function ChatThread({ history, onSend, busy, lastKind, backend }: Props) {
  const [draft, setDraft] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const message = draft.trim();
    if (!message || busy) return;
    onSend(message);
    setDraft("");
  }

  return (
    <div className="chat">
      <div className="chat-head">
        <h3>Ask or change</h3>
        {backend && (
          <span className="muted">
            answered by <strong>{backend}</strong>
            {lastKind && <> · {lastKind === "modification" ? "re-solved" : "no change"}</>}
          </span>
        )}
      </div>

      {history.length === 0 ? (
        <div className="chat-examples">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="example"
              disabled={busy}
              onClick={() => onSend(example)}
            >
              {example}
            </button>
          ))}
        </div>
      ) : (
        <ul className="chat-thread">
          {history.map((m, i) => (
            <li key={i} className={`bubble ${m.role}`}>
              {m.content}
            </li>
          ))}
          {busy && <li className="bubble assistant muted">Thinking…</li>}
        </ul>
      )}

      <form className="chat-form" onSubmit={submit}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="e.g. why is 15-213 on Mondays? · make it lighter"
          disabled={busy}
        />
        <button type="submit" disabled={busy || !draft.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
