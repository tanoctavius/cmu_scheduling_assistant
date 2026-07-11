// Types mirroring the backend API (see backend/app/main.py).

export interface StudentProfile {
  major: string;
  expected_grad: string;
  completed_courses: string[];
  interests: string[];
  career_goals?: string[];
  commitments?: unknown[];
}

export interface FoundationCourse {
  course_num: string;
  title: string;
  units: number;
}

export interface SurveyResponse {
  major: string;
  foundation_courses: FoundationCourse[];
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

export interface AskResult {
  sections: Section[];
  total_units: number;
  total_workload_hours: number;
  score: number;
  classifications: Record<string, string>;
  fit_rank: number | null;
  explanation: string | null;
  verified_claims: Claim[];
  stripped_claim_count: number;
  confirmation_questions: ConfirmationQuestion[];
  requirements_advanced: GroupRef[];
}

export interface AskResponse {
  question: string;
  route: string; // "structured" | "semantic"
  llm_backend: string; // "none" | "stub" | "anthropic"
  results: AskResult[];
  disclaimer: string;
}
