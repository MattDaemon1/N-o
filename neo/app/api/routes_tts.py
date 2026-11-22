"""Local TTS (Voix de NÉO) status, vocal modes, voice download, test, and STOP VOIX routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.state_manager import VocalMode

router = APIRouter(prefix="/api/tts", tags=["tts"])


class VocalModePayload(BaseModel):
    vocal_mode: VocalMode


class SpeakPayload(BaseModel):
    text: str = Field(min_length=1, max_length=1500)


class TestVoicePayload(BaseModel):
    text: str | None = Field(default=None, max_length=500)


class VoiceSelectionPayload(BaseModel):
    voice_id: str = Field(min_length=1, max_length=160)


@router.get("/status")
async def get_tts_status(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    return rt.tts_service.get_status()


@router.post("/mode")
async def set_vocal_mode(request: Request, body: VocalModePayload) -> dict[str, Any]:
    rt = request.app.state.runtime
    if body.vocal_mode == VocalMode.SILENCIEUX:
        rt.tts_service.interrupt("Passage en mode vocal SILENCIEUX.")
    rt.config_manager.update({"vocal_mode": body.vocal_mode.value})
    return {
        "ok": True,
        "vocal_mode": body.vocal_mode.value,
        "status": rt.tts_service.get_status(refresh_inventory=False),
    }


@router.post("/stop")
async def stop_voice_immediately(request: Request) -> dict[str, Any]:
    """Global 'STOP VOIX' endpoint: interrupts TTS immediately without stopping mic/VAD/STT."""
    rt = request.app.state.runtime
    interrupted = rt.tts_service.interrupt("Arrêt vocal immédiat demandé par le formateur (STOP VOIX).")
    return {
        "ok": True,
        "interrupted": interrupted,
        "mic_active": rt.state_manager.mic_active,
        "listening_enabled": rt.state_manager.listening_enabled,
        "tts": rt.tts_service.get_status(refresh_inventory=False),
    }


@router.post("/speak")
async def speak_on_demand(request: Request, body: SpeakPayload) -> dict[str, Any]:
    """Speaks an explicit text when triggered by the trainer ('Faire prononcer par NÉO')."""
    rt = request.app.state.runtime
    return rt.tts_service.speak_on_trainer_request(body.text)


@router.post("/test")
async def test_voice(request: Request, body: TestVoicePayload | None = None) -> dict[str, Any]:
    rt = request.app.state.runtime
    txt = body.text if body is not None else None
    return rt.tts_service.test_voice(txt)


@router.get("/voices")
async def list_voices(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    return rt.tts_service.get_status()


@router.post("/voices/select")
async def select_voice(request: Request, body: VoiceSelectionPayload) -> dict[str, Any]:
    rt = request.app.state.runtime
    rt.tts_service.unload_resources()
    rt.config_manager.update({"tts_voice": body.voice_id})
    valid, err, _ = rt.tts_service.voice_manager.validate_voice(body.voice_id)
    return {
        "ok": True,
        "selected_voice": body.voice_id,
        "installed": valid,
        "error": err,
        "status": rt.tts_service.get_status(),
    }


@router.post("/voices/download")
async def download_voice_explicitly(request: Request, body: VoiceSelectionPayload) -> dict[str, Any]:
    """Explicit user-requested French Piper voice installation (never auto-downloaded)."""
    rt = request.app.state.runtime
    ok, msg = await rt.tts_service.voice_manager.download_voice_explicitly(body.voice_id)
    if ok:
        rt.config_manager.update({"tts_voice": body.voice_id})
    return {
        "ok": ok,
        "message": msg,
        "status": rt.tts_service.get_status(),
    }


@router.delete("/voices/{voice_id}")
async def delete_voice(request: Request, voice_id: str) -> dict[str, Any]:
    rt = request.app.state.runtime
    if rt.config_manager.config.tts_voice == voice_id:
        rt.tts_service.unload_resources()
    ok, msg = rt.tts_service.voice_manager.delete_voice(voice_id)
    return {"ok": ok, "message": msg, "status": rt.tts_service.get_status()}


@router.post("/unload")
async def unload_tts_model(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    rt.tts_service.unload_resources()
    return {"ok": True, "status": rt.tts_service.get_status()}
