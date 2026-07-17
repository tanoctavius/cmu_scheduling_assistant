import type {
  ChatMessage,
  ChatResponse,
  RecommendResponse,
  ScheduleConstraints,
  StudentProfile,
  SurveyResponse,
} from "./types";

// Backend base URL comes from an env var (see .env.example); defaults to local dev.
export const BACKEND_URL: string =
  (import.meta.env.VITE_BACKEND_URL as string | undefined) ?? "http://localhost:8000";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Request to ${path} failed (${res.status})`);
  }
  return (await res.json()) as T;
}

export function getSurvey(profile: StudentProfile): Promise<SurveyResponse> {
  return post<SurveyResponse>("/survey", profile);
}

// One conversational turn. The LLM classifies the turn and proposes constraints;
// the deterministic solver rebuilds the calendar and the verifier gates every
// claim. Conversation state is client-held (`history`, `constraints`) and echoed
// back each turn — the server keeps no session.
export function chat(args: {
  profile: StudentProfile;
  message: string;
  answers: Record<string, boolean>;
  history: ChatMessage[];
  constraints: ScheduleConstraints;
  selected: number;
}): Promise<ChatResponse> {
  return post<ChatResponse>("/chat", args);
}

// Deterministic top-K schedules + confirmation questions (no LLM). Seeds the
// prerequisite-confirmation panel.
export function recommend(profile: StudentProfile): Promise<RecommendResponse> {
  return post<RecommendResponse>("/recommend", profile);
}

// Apply the student's per-prereq answers and re-run the cascade (classifier ->
// solver). `answers` maps a prerequisite course number to whether it's been
// taken. Goes straight to the deterministic core — never through the LLM.
export function confirm(
  profile: StudentProfile,
  answers: Record<string, boolean>,
): Promise<RecommendResponse> {
  return post<RecommendResponse>("/confirm", { profile, answers });
}
