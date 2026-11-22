"""Persistent configuration read, update, and reset routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    return {
        "config": rt.config_manager.config.model_dump(),
        "warning": rt.config_manager.last_warning,
    }


@router.put("")
async def update_settings(request: Request, patch: dict[str, Any]) -> dict[str, Any]:
    rt = request.app.state.runtime
    try:
        updated = rt.apply_config_update(patch)
        return {"ok": True, "config": updated.model_dump()}
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/reset")
async def reset_settings(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    reset_cfg = rt.reset_config_defaults()
    return {"ok": True, "config": reset_cfg.model_dump()}
