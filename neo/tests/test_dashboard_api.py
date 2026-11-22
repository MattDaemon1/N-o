"""FastAPI dashboard, settings, model selection, mic selection, and session API tests."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.ai.ollama_client import OllamaModelInfo
from app.audio.capture import MicrophoneDevice
from app.main import create_app


def test_config_corruption_recovers_defaults(tmp_path: Path):
    cfg_path = tmp_path / "dashboard_config.json"
    cfg_path.write_text("{corrompu!!!", encoding="utf-8")

    app = create_app(config_path=cfg_path)
    with TestClient(app) as client:
        res = client.get("/api/settings")
        assert res.status_code == 200
        data = res.json()
        assert data["warning"] is not None
        assert data["config"]["mode"] == "ACTIF"
        assert (tmp_path / "dashboard_config.corrupted.bak").exists()


def test_dashboard_api_session_modes_models_mics_and_history(tmp_path: Path):
    cfg_path = tmp_path / "dashboard_config.json"
    app = create_app(config_path=cfg_path)

    with (
        patch.object(
            app.state.runtime.ollama_client,
            "list_models",
            AsyncMock(
                return_value=(
                    True,
                    [
                        OllamaModelInfo(
                            name="llama3.2:1b",
                            size_bytes=1_300_000_000,
                            size_label="1.2 Go",
                            family="llama",
                            parameter_size="1B",
                            quantization="Q4_K_M",
                        )
                    ],
                    None,
                )
            ),
        ),
        patch("app.api.routes_audio.AudioCapture.list_devices", return_value=([
            MicrophoneDevice(index=1, name="Micro USB Salle", max_input_channels=1, default_samplerate=16000)
        ], None)),
    ):
        with TestClient(app) as client:
            # Dashboard HTML loads
            html_res = client.get("/")
            assert html_res.status_code == 200
            assert "NÉO" in html_res.text

            # List & select Ollama model
            m_res = client.get("/api/models")
            assert m_res.status_code == 200
            assert m_res.json()["models"][0]["name"] == "llama3.2:1b"

            sel_res = client.post("/api/models/select", json={"model_name": "llama3.2:1b"})
            assert sel_res.status_code == 200
            assert sel_res.json()["selected_model"] == "llama3.2:1b"

            # List & select Microphone
            mic_res = client.get("/api/audio/devices")
            assert mic_res.status_code == 200
            assert mic_res.json()["devices"][0]["name"] == "Micro USB Salle"

            mic_sel = client.post("/api/audio/select", json={"device_index": 1, "device_name": "Micro USB Salle"})
            assert mic_sel.status_code == 200

            # Session lifecycle & modes
            assert client.post("/api/session/start").json()["ok"] is True
            assert client.post("/api/session/mode", json={"mode": "PASSIF"}).json()["mode"] == "PASSIF"
            assert client.post("/api/session/pause").json()["ok"] is True
            assert client.post("/api/session/resume").json()["ok"] is True

            # Simulation scenario runs through behavior engine & logs history
            sim = client.post("/api/session/simulate", json={"scenario_id": "hors_sujet"})
            assert sim.status_code == 200
            assert sim.json()["intervened"] is False

            state_res = client.get("/api/dashboard/state").json()
            assert len(state_res["history"]) >= 1

            # Clear history & stop session
            assert client.delete("/api/session/history").json()["ok"] is True
            assert client.get("/api/dashboard/state").json()["history"] == []
            assert client.post("/api/session/stop").json()["ok"] is True


def test_tts_api_endpoints_and_mode_switch_preserves_proposal(tmp_path: Path):
    cfg_path = tmp_path / "dashboard_config.json"
    app = create_app(config_path=cfg_path)

    with TestClient(app) as client:
        # TTS status & vocal modes
        st = client.get("/api/tts/status")
        assert st.status_code == 200
        assert st.json()["vocal_mode"] == "ASSISTANT"

        m_res = client.post("/api/tts/mode", json={"vocal_mode": "SILENCIEUX"})
        assert m_res.status_code == 200
        assert m_res.json()["vocal_mode"] == "SILENCIEUX"

        # Speaking while SILENCIEUX or disabled is cleanly rejected without error 500
        spk = client.post("/api/tts/speak", json={"text": "Bonjour test"})
        assert spk.status_code == 200
        assert spk.json()["spoken"] is False

        # Global STOP VOIX leaves mic/listening state intact and succeeds cleanly
        stop_res = client.post("/api/tts/stop")
        assert stop_res.status_code == 200
        assert stop_res.json()["ok"] is True

        # Switching behavior mode mid-session preserves active PROPOSITION state
        from app.core.state_manager import NeoState, ProposalRecord

        rt = app.state.runtime
        rt.state_manager.session_active = True
        rt.state_manager.active_proposal = ProposalRecord(
            id="prop-99",
            created_at="10:00:00",
            transcript="Question test",
            event_type="QUESTION",
            analysis="Analyse",
            decision="OK",
            intervention_type="Reformulation",
            private_trainer_note="Note",
            learner_response="Réponse",
            confidence=0.9,
            processing_ms=50,
        )
        rt.state_manager.set_state(NeoState.PROPOSITION)
        mode_res = client.post("/api/session/mode", json={"mode": "SUR_DEMANDE"})
        assert mode_res.status_code == 200
        assert mode_res.json()["neo_state"] == NeoState.PROPOSITION.value
        assert rt.state_manager.active_proposal is not None


def test_dashboard_polling_caches_inventory_and_explicit_diagnostics_refreshes(tmp_path: Path):
    cfg_path = tmp_path / "dashboard_config.json"
    app = create_app(config_path=cfg_path)
    rt = app.state.runtime

    with (
        patch(
            "app.services.diagnostics_service.AudioCapture.list_devices",
            return_value=([], None),
        ) as dev_mock,
        patch.object(rt.stt, "list_installed_models", return_value=["tiny"]) as stt_mock,
        patch.object(rt.tts_service.voice_manager, "list_voices", return_value=[]) as voice_mock,
        patch.object(rt.ollama_client, "list_models", AsyncMock(return_value=(False, [], None))),
    ):
        with TestClient(app) as client:
            for _ in range(4):
                res = client.get("/api/dashboard/state")
                assert res.status_code == 200
                assert res.json()["stt"]["installed_models"] == ["tiny"]

            assert dev_mock.call_count == 1
            assert stt_mock.call_count == 1
            assert voice_mock.call_count == 1

            # Explicit diagnostic endpoint always refreshes immediately
            diag_res = client.get("/api/diagnostics")
            assert diag_res.status_code == 200
            assert dev_mock.call_count == 2
            assert stt_mock.call_count == 2
            assert voice_mock.call_count == 2

