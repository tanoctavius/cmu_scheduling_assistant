import type { AskResponse, StudentProfile, SurveyResponse } from "./types";

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

export function ask(profile: StudentProfile, question: string): Promise<AskResponse> {
  return post<AskResponse>("/ask", { profile, question });
}
