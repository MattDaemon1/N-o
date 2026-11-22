"""Microphone devices, audio testing, and Faster-Whisper STT management routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.audio.capture import AudioCapture
from app.audio.stt import SUPPORTED_WHISPER_MODELS

router = APIRouter(prefix="/api/audio", tags=["audio"])


class SelectMicPayload(BaseModel):
    device_index: int | None = None
    device_name: str = ""


class SttModelPayload(BaseModel):
    model_name: str
    compute_type: str = "int8"


@router.get("/devices")
async def list_audio_devices(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    devices, err = AudioCapture.list_devices()
    rt.diagnostics_service.invalidate_inventory_cache()
    cfg = rt.config_manager.config
    return {
        "devices": [d.to_dict() for d in devices],
        "selected_device_index": cfg.mic_device_index,
        "selected_device_name": cfg.mic_device_name,
        "error": err,
    }


@router.post("/select")
async def select_audio_device(request: Request, body: SelectMicPayload) -> dict[str, Any]:
    rt = request.app.state.runtime
    rt.config_manager.update(
        {
            "mic_device_index": body.device_index,
            "mic_device_name": body.device_name,
        }
    )
    rt.diagnostics_service.invalidate_inventory_cache()
    if rt.state_manager.listening_enabled and rt.state_manager.session_active:
        rt.audio_pipeline.start()
    return {"ok": True, "selected_device_index": body.device_index}


@router.post("/test")
async def test_audio_device(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    cfg = rt.config_manager.config
    was_running = rt.audio_capture.is_running
    if was_running:
        rt.audio_pipeline.stop()

    result = await asyncio.to_thread(
        rt.audio_capture.test_microphone,
        cfg.mic_device_index,
        cfg.sample_rate,
        1.2,
    )

    if was_running and rt.state_manager.listening_enabled:
        rt.audio_pipeline.start()
    return result


@router.get("/stt-models")
async def list_stt_models(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    installed = rt.stt.list_installed_models()
    rt.diagnostics_service.invalidate_inventory_cache()
    cfg = rt.config_manager.config
    return {
        "supported": SUPPORTED_WHISPER_MODELS,
        "installed": installed,
        "selected_model": cfg.stt_model,
        "compute_type": cfg.stt_compute_type,
        "language": cfg.stt_language,
    }


@router.post("/stt-models/select")
async def select_stt_model(request: Request, body: SttModelPayload) -> dict[str, Any]:
    rt = request.app.state.runtime
    if body.model_name not in SUPPORTED_WHISPER_MODELS:
        return {"ok": False, "error": f"Modèle non pris en charge : {body.model_name}"}
    rt.config_manager.update(
        {
            "stt_model": body.model_name,
            "stt_compute_type": body.compute_type,
        }
    )
    rt.diagnostics_service.invalidate_inventory_cache()
    return {
        "ok": True,
        "selected_model": body.model_name,
        "installed": rt.stt.is_model_installed(body.model_name),
    }


@router.post("/stt-models/download")
async def download_stt_model_explicitly(request: Request, body: SttModelPayload) -> dict[str, Any]:
    """Explicit user-requested Faster-Whisper model installation (never called automatically)."""
    rt = request.app.state.runtime
    ok, msg = await asyncio.to_thread(
        rt.stt.download_model_explicitly,
        body.model_name,
        body.compute_type,
    )
    if ok:
        rt.config_manager.update({"stt_model": body.model_name})
    rt.diagnostics_service.invalidate_inventory_cache()
    return {"ok": ok, "message": msg, "installed": rt.stt.list_installed_models()}
