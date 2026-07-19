import type { Claim, ScheduleOut } from "../types";

interface Props {
  schedule: ScheduleOut | null;
}

function claimText(claim: Claim): string {
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

// Why the selected schedule was built, beside the calendar it describes.
//
// Every green checkmark here is a claim that PASSED the deterministic claim
// verifier against this exact schedule (see backend/app/rationale.py) — these are
// checked facts, not model prose. The panel re-renders whenever the selected
// schedule changes, because it renders straight from that schedule's rationale.
export function RationalePanel({ schedule }: Props) {
  if (!schedule) return null;

  const { rationale, requirements_advanced } = schedule;

  return (
    <div className="rationale-panel">
      <h3>Why this schedule</h3>
      <p className="rationale-summary">{rationale.summary}</p>

      {rationale.verified_claims.length > 0 && (
        <section aria-label="Verified facts">
          <p className="panel-label">
            ✓ Verified facts
            <span className="panel-label-hint">checked against this schedule</span>
          </p>
          <div className="claims" role="list">
            {rationale.verified_claims.map((c, i) => (
              <span
                className="chip verified"
                role="listitem"
                key={i}
                title="Checked by the deterministic claim verifier"
              >
                ✓ {claimText(c)}
              </span>
            ))}
          </div>
        </section>
      )}

      {requirements_advanced.length > 0 && (
        <section aria-label="Requirement coverage">
          <p className="panel-label">
            ◆ Requirement coverage
            <span className="panel-label-hint">degree groups this advances</span>
          </p>
          <div className="claims" role="list">
            {requirements_advanced.map((g) => (
              <span
                className="chip requirement"
                role="listitem"
                key={g.id}
                title="Advances a degree requirement"
              >
                ◆ {g.name}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Non-zero means a fact derived from this schedule failed its own check —
          a real bug signal, so surface it rather than hide it. */}
      {rationale.stripped_claim_count > 0 && (
        <p className="error">
          {rationale.stripped_claim_count} claim(s) failed verification and were
          withheld.
        </p>
      )}
    </div>
  );
}
