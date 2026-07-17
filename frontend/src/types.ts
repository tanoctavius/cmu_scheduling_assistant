// Types mirroring the backend API (see backend/app/main.py).

export interface StudentProfile {
  major: string;
  expected_grad: string;
  completed_courses: string[];
  interests: string[];
  career_goals?: string[];
  commitments?: unknown[];
}

export interface ChecklistItem {
  course_num: string;
  title: string;
  units: number | null;
}

export interface ChecklistGroup {
  header: string;
  courses: ChecklistItem[];
}

export interface SurveyResponse {
  major: string;
  checklist: ChecklistGroup[];
}

export interface Section {
  course_num: string;
  title: string;
  units: number;
  section_id: string;
  days: string[];
  begin: string; // "HH:MM:SS"
  end: string;
  location: string;
}

// A verified factual claim. The discriminating field is `type`; other fields
// vary by claim type (e.g. `value`, `day`, `course_num`).
export interface Claim {
  type: "no_class_on" | "total_units" | "includes_course" | "no_conflicts";
  value?: number;
  day?: string;
  course_num?: string;
}

export interface ConfirmationQuestion {
  course_num: string;
  title: string;
  missing_prereqs: string[];
  question: string;
}

export interface GroupRef {
  id: string;
  name: string;
}

// Why a schedule was built, plus the facts about it that PASSED the claim
// verifier. `verified_claims` are verifier outputs — never LLM free-text — so
// the green checkmarks in the rationale panel are always checked facts.
export interface Rationale {
  summary: string;
  verified_claims: Claim[];
  stripped_claim_count: number;
}

// One solved schedule as returned by /recommend, /confirm, and /chat. Always the
// deterministic solver's output — no model ever authors or edits this.
export interface ScheduleOut {
  sections: Section[];
  total_units: number;
  total_workload_hours: number;
  score: number;
  classifications: Record<string, string>;
  requirements_advanced: GroupRef[];
  rationale: Rationale;
}

// Response of the deterministic cascade endpoints. `/recommend` seeds the panel;
// `/confirm` returns the re-solved schedules after a prereq answer.
export interface RecommendResponse {
  schedules: ScheduleOut[];
  confirmation_questions: ConfirmationQuestion[];
  disclaimer: string;
}

// --- Chat --------------------------------------------------------------------

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

// The closed vocabulary of schedule changes the chat can ask the solver for.
// The LLM may only fill these fields; it cannot place or move a section.
export interface ScheduleConstraints {
  avoid_days: string[];
  max_units: number | null;
  no_class_before: string | null;
  no_class_after: string | null;
  exclude_courses: string[];
}

export const EMPTY_CONSTRAINTS: ScheduleConstraints = {
  avoid_days: [],
  max_units: null,
  no_class_before: null,
  no_class_after: null,
  exclude_courses: [],
};

export interface ChatResponse {
  reply: string;
  kind: "question" | "modification";
  llm_backend: string; // "stub" | "groq" | any provider added later
  // The calendar after this turn: unchanged for a question, re-solved for a
  // modification. Always solver output.
  schedules: ScheduleOut[];
  constraints: ScheduleConstraints;
  constraints_relaxed: boolean;
  verified_claims: Claim[];
  stripped_claim_count: number;
  confirmation_questions: ConfirmationQuestion[];
  history: ChatMessage[];
  disclaimer: string;
}
