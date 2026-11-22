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
        prev_mode = rt.config_manager.config.mode
        updated = rt.config_manager.update(patch)
        rt.ollama_client.set_base_url(updated.ollama_url)
        rt.segment_queue.set_max_pending(updated.max_pending_segments)
        rt.tts_service.worker.set_auto_unload_seconds(updated.tts_auto_unload_seconds)

        if "mode" in patch and updated.mode != prev_mode:
            rt.session_controller.on_behavior_mode_changed(updated.mode)
        if not updated.tts_enabled:
            rt.tts_service.unload_resources()
        elif updated.vocal_mode == "SILENCIEUX":
            rt.tts_service.interrupt("Mode vocal SILENCIEUX sélectionné.")

        return {"ok": True, "config": updated.model_dump()}
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/reset")
async def reset_settings(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    rt.tts_service.unload_resources()
    reset_cfg = rt.config_manager.reset_defaults()
    rt.ollama_client.set_base_url(reset_cfg.ollama_url)
    rt.segment_queue.set_max_pending(reset_cfg.max_pending_segments)
    return {"ok": True, "config": reset_cfg.model_dump()}
