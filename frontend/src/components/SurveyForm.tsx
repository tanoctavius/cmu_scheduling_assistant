import { useState } from "react";
import type { StudentProfile } from "../types";

interface Props {
  onSubmit: (profile: StudentProfile) => void;
  busy: boolean;
}

// Step 1: the short survey. Collects the fields the backend's /survey needs.
export function SurveyForm({ onSubmit, busy }: Props) {
  const [major, setMajor] = useState("Computer Science");
  const [expectedGrad, setExpectedGrad] = useState("2027");
  const [interests, setInterests] = useState("machine learning, systems");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit({
      major: major.trim(),
      expected_grad: expectedGrad.trim(),
      completed_courses: [],
      interests: interests
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    });
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>1 · Tell us about you</h2>
      <label>
        Major
        <input value={major} onChange={(e) => setMajor(e.target.value)} required />
      </label>
      <label>
        Expected graduation
        <input
          value={expectedGrad}
          onChange={(e) => setExpectedGrad(e.target.value)}
          required
        />
      </label>
      <label>
        Interests (comma-separated)
        <input value={interests} onChange={(e) => setInterests(e.target.value)} />
      </label>
      <button type="submit" disabled={busy}>
        {busy ? "Loading…" : "Continue"}
      </button>
    </form>
  );
}
