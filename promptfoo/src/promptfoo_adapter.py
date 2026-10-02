"""Minimal HTTP adapter for running Promptfoo evals against the Azure-backed app."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

try:
    from promptfoo.src.promptfoo_wrapper import PromptfooHttpWrapper
except ModuleNotFoundError:  # pragma: no cover - fallback for local subproject execution
    from src.promptfoo_wrapper import PromptfooHttpWrapper

app = FastAPI(title="Promptfoo adapter")


class EvalRequest(BaseModel):
    query: str
    step_number: str | None = None


class EvalResponse(BaseModel):
    response_message: str
    step_number: str | None = None


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/invoke", response_model=EvalResponse)
async def invoke(request: EvalRequest):
    wrapper = PromptfooHttpWrapper()
    try:
        result = await wrapper.invoke(query=request.query, step_number=request.step_number)
        return EvalResponse(
            response_message=wrapper.extract_output(result),
            step_number=request.step_number,
        )
    except Exception as exc:  # pragma: no cover - defensive path
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        await wrapper.close()
