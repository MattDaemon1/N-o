"""Session control, trainer commands, proposal actions, history, and simulation routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.state_manager import BehaviorMode

router = APIRouter(prefix="/api/session", tags=["session"])


class ModePayload(BaseModel):
    mode: BehaviorMode


class TogglePayload(BaseModel):
    enabled: bool


class CommandPayload(BaseModel):
    command: str = Field(min_length=1, max_length=1000)
    intervention_hint: str | None = Field(default=None, max_length=120)


class SimulatePayload(BaseModel):
    scenario_id: str


class ProposalActionPayload(BaseModel):
    action: str


@router.post("/start")
async def start_session(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    state = rt.session_controller.start_session(enable_listening=True)
    return {"ok": True, "neo_state": state.value}


@router.post("/pause")
async def pause_session(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    state = rt.session_controller.pause_session()
    return {"ok": True, "neo_state": state.value}


@router.post("/resume")
async def resume_session(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    state = rt.session_controller.resume_session()
    return {"ok": True, "neo_state": state.value}


@router.post("/stop")
async def stop_session(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    state = rt.session_controller.stop_session()
    return {"ok": True, "neo_state": state.value}


@router.post("/toggle-neo")
async def toggle_neo(request: Request, body: TogglePayload) -> dict[str, Any]:
    rt = request.app.state.runtime
    state = rt.session_controller.set_neo_enabled(body.enabled)
    return {"ok": True, "neo_state": state.value, "mode": rt.config_manager.config.mode}


@router.post("/toggle-listen")
async def toggle_listen(request: Request, body: TogglePayload) -> dict[str, Any]:
    rt = request.app.state.runtime
    if body.enabled:
        ok = rt.session_controller.enable_listening()
        return {"ok": ok, "listening_enabled": rt.state_manager.listening_enabled}
    rt.session_controller.disable_listening()
    return {"ok": True, "listening_enabled": False}


@router.post("/mode")
async def set_mode(request: Request, body: ModePayload) -> dict[str, Any]:
    rt = request.app.state.runtime
    state = rt.session_controller.on_behavior_mode_changed(body.mode.value)
    return {"ok": True, "mode": rt.config_manager.config.mode, "neo_state": state.value}


@router.post("/interrupt")
async def interrupt_neo(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    state = rt.session_controller.interrupt()
    return {"ok": True, "neo_state": state.value}


@router.post("/command")
async def trainer_command(request: Request, body: CommandPayload) -> dict[str, Any]:
    rt = request.app.state.runtime
    rt.tts_service.interrupt("Nouvelle demande directe du formateur.")
    return await rt.pedagogical_service.process_transcript(
        transcript=body.command,
        speaker="Formateur",
        explicit_trainer_request=True,
        intervention_hint=body.intervention_hint,
        is_simulated=False,
    )


@router.post("/simulate")
async def run_simulation(request: Request, body: SimulatePayload) -> dict[str, Any]:
    rt = request.app.state.runtime
    return await rt.pedagogical_service.run_simulation_scenario(body.scenario_id)


@router.post("/proposals/{proposal_id}/action")
async def proposal_action(
    request: Request, proposal_id: str, body: ProposalActionPayload
) -> dict[str, Any]:
    rt = request.app.state.runtime
    return await rt.pedagogical_service.handle_proposal_action(proposal_id, body.action)


@router.delete("/history")
async def clear_history(request: Request) -> dict[str, Any]:
    rt = request.app.state.runtime
    rt.event_manager.clear()
    rt.state_manager.reset_session_memory()
    return {"ok": True}
