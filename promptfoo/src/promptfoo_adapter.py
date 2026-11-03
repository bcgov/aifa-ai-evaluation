"""Minimal HTTP adapter for running Promptfoo evals against the Azure-backed app."""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from aifa_pyrit.logging_utils import setup_logger

try:
    from promptfoo.src.promptfoo_wrapper import PromptfooHttpWrapper
except ModuleNotFoundError:  # pragma: no cover - fallback for local subproject execution
    from src.promptfoo_wrapper import PromptfooHttpWrapper

logger = setup_logger("promptfoo.adapter", log_dir=os.getenv("APP_LOG_DIR"))
app = FastAPI(title="Promptfoo adapter")


class EvalRequest(BaseModel):
    query: str
    step_number: str | None = None


class EvalResponse(BaseModel):
    response_message: str
    step_number: str | None = None


@app.get("/health")
def health_check():
    logger.info("promptfoo_adapter_health_check")
    return {"status": "ok"}


@app.post("/invoke", response_model=EvalResponse)
async def invoke(request: EvalRequest):
    logger.info(
        "promptfoo_adapter_invoke_start query_preview=%s step_number=%s",
        request.query[:200] if request.query else "",
        request.step_number,
    )
    wrapper = PromptfooHttpWrapper()
    try:
        result = await wrapper.invoke(query=request.query, step_number=request.step_number)
        response_message = wrapper.extract_output(result)
        logger.info(
            "promptfoo_adapter_invoke_success step_number=%s response_preview=%s",
            request.step_number,
            response_message[:2000] if response_message else "",
        )
        return EvalResponse(
            response_message=response_message,
            step_number=request.step_number,
        )
    except Exception as exc:  # pragma: no cover - defensive path
        logger.exception(
            "promptfoo_adapter_invoke_failed step_number=%s query_preview=%s",
            request.step_number,
            request.query[:200] if request.query else "",
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        await wrapper.close()
