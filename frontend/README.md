# cmu-scheduler frontend

A small React (Vite + TypeScript) demo UI: a survey form, a prereq tick-off
checklist, a chat box that calls the backend's `/ask`, and a week-grid rendering
of the returned schedules. Styling is intentionally clean and minimal — it's here
to demo the pipeline, not to dazzle.

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

- `src/api.ts` — typed fetch wrappers; base URL from `VITE_BACKEND_URL`.
- `src/types.ts` — types mirroring the backend API.
- `src/components/` — `SurveyForm`, `PrereqChecklist`, `ChatBox`, `WeekGrid`.
