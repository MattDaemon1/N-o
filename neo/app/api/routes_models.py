"""Ollama model discovery, selection, and ping test routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/models", tags=["models"])


class SelectModelPayload(BaseModel):
    model_name: str


class TestModelPayload(BaseModel):
    model_name: str | None = None


@router.get("")
async def list_ollama_models(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    return await rt.model_manager.refresh()


@router.post("/select")
async def select_ollama_model(request: Request, body: SelectModelPayload) -> dict[str, Any]:
    rt = request.app.state.runtime
    return rt.model_manager.select_model(body.model_name)


@router.post("/test")
async def test_ollama_model(request: Request, body: TestModelPayload) -> dict[str, Any]:
    rt = request.app.state.runtime
    return await rt.model_manager.test_selected_model(body.model_name)
