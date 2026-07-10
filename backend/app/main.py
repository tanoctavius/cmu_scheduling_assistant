"""FastAPI application entrypoint for cmu-scheduler.

Stage 0 skeleton: only a health endpoint. Feature logic (solver, verifier,
classifier, orchestrator) is added in later stages.
"""

from fastapi import FastAPI

app = FastAPI(title="cmu-scheduler")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
