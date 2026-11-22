"""Dashboard HTML view, live state snapshot, and diagnostics routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.pedagogical_service import SIMULATION_SCENARIOS

router = APIRouter()
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html", {})


@router.get("/api/dashboard/state")
async def get_dashboard_state(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    cfg = rt.config_manager.config
    st = rt.state_manager
    snap = await rt.diagnostics_service.snapshot(
        refresh_ollama=False,
        refresh_inventory=False,
    )

    return {
        "neo_state": st.state.value,
        "mode": cfg.mode,
        "vocal_mode": cfg.vocal_mode,
        "tts_enabled": cfg.tts_enabled,
        "session_active": st.session_active,
        "session_paused": st.session_paused,
        "listening_enabled": st.listening_enabled,
        "mic_active": st.mic_active,
        "audio_level": round(st.audio_level, 3),
        "cooldown_remaining": st.cooldown_remaining(cfg.cooldown_seconds),
        "last_error": st.last_error,
        "last_silence_reason": st.last_silence_reason,
        "config_warning": rt.config_manager.last_warning,
        "training_context": cfg.training_context.model_dump(),
        "active_proposal": st.active_proposal.to_dict() if st.active_proposal else None,
        "published_to_learners": st.published_to_learners[:10],
        "history": rt.event_manager.list_events(limit=80),
        "metrics": {
            "segments_processed": st.metrics.segments_processed,
            "errors_count": st.metrics.errors_count,
            "interventions_count": st.metrics.interventions_count,
            "accepted_count": st.metrics.accepted_count,
            "ignored_count": st.metrics.ignored_count,
            "tts_spoken_count": st.metrics.tts_spoken_count,
            "tts_interrupted_count": st.metrics.tts_interrupted_count,
            "last_transcription_ms": st.metrics.last_transcription_ms,
            "last_llm_ms": st.metrics.last_llm_ms,
            "last_tts_ms": st.metrics.last_tts_ms,
        },
        "system": snap["system"],
        "ollama": snap["ollama"],
        "stt": snap["stt"],
        "audio": snap["audio"],
        "tts": snap["tts"],
        "simulation_scenarios": [
            {"id": sid, "label": data["label"], "transcript": data["transcript"]}
            for sid, data in SIMULATION_SCENARIOS.items()
        ],
    }


@router.get("/api/diagnostics")
async def get_diagnostics(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    return await rt.diagnostics_service.snapshot(
        refresh_ollama=True,
        refresh_inventory=True,
    )


@router.post("/api/diagnostics/run")
async def run_diagnostics(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    return await rt.diagnostics_service.run_global_check()
