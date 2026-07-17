# cmu-scheduler frontend

A small React (Vite + TypeScript) demo UI in three parts: a survey form, a prereq
tick-off checklist, and the schedule workspace — a week-grid calendar beside a
right-hand panel (rationale + verified facts + prereq confirmation controls),
with a chat below it that can answer questions about the calendar or ask for
changes to it. Styling is intentionally clean and minimal — it's here to demo the
pipeline, not to dazzle.

The UI never computes a schedule. Calendars come from the backend's solver, the
green checkmarks are claim-verifier output, and a chat "modification" is just the
solver re-run under new constraints.

## Run

```bash
cd frontend
cp .env.example .env      # set VITE_BACKEND_URL if the backend isn't on :8000
npm install
npm run dev               # http://localhost:5173
```

The backend must be running (see the [top-level README](../README.md)); the app
reads its URL from `VITE_BACKEND_URL`.

## Scripts

- `npm run dev` — dev server with HMR
- `npm run build` — type-check + production build to `dist/`
- `npm run typecheck` — `tsc --noEmit` (used by `make lint`)

## Layout

- `src/api.ts` — typed fetch wrappers (`/survey`, `/recommend`, `/confirm`,
  `/chat`); base URL from `VITE_BACKEND_URL`.
- `src/types.ts` — types mirroring the backend API.
- `src/components/` — `SurveyForm`, `PrereqChecklist`, `SchedulePanel` (the
  workspace), `WeekGrid`, `RationalePanel`, `ConfirmationPanel`, `ChatThread`.

Conversation state (`history`, `constraints`) is held in `SchedulePanel` and
echoed to the server on each turn — the backend keeps no session, so a restart
mid-conversation costs nothing.
