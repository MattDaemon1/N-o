"""Phase H operational stress tests, anti-echo validation, and 12 pedagogical behavior scenarios."""

from __future__ import annotations

import asyncio
import json
import struct
import time
from pathlib import Path

from app.ai.model_manager import ModelManager
from app.ai.ollama_client import OllamaClient
from app.audio.capture import AudioCapture
from app.audio.pipeline import AudioPipeline
from app.audio.segmentation import AudioSegment, SegmentQueueManager
from app.audio.stt import FasterWhisperSTT, TranscriptionResult
from app.audio.vad import VoiceActivityDetector
from app.config.config_manager import ConfigManager
from app.core.decision_engine import DecisionEngine
from app.core.event_manager import EventManager
from app.core.session_controller import SessionController
from app.core.state_manager import BehaviorMode, NeoState, StateManager, VocalMode
from app.services.pedagogical_service import PedagogicalService
from app.services.transcription_service import TranscriptionService
from app.services.tts_service import TTSService
from app.tts.engine import PiperTTSEngine, SynthesizedAudio
from app.tts.voice_manager import VoiceManager


def _create_dummy_voice(voices_dir: Path, voice_id: str = "fr_FR-siwis-medium") -> None:
    voices_dir.mkdir(parents=True, exist_ok=True)
    (voices_dir / f"{voice_id}.onnx").write_bytes(b"ONNX" * 256)
    (voices_dir / f"{voice_id}.onnx.json").write_text(
        json.dumps({"audio": {"sample_rate": 22050}}),
        encoding="utf-8",
    )


def _pcm(amplitude: int, samples: int = 1600) -> bytes:
    return struct.pack(f"<{samples}h", *([amplitude] * samples))


def _build_stack(tmp_path: Path, *, with_voice: bool = True):
    cfg_mgr = ConfigManager(config_path=tmp_path / "dashboard_config.json")
    cfg_mgr.update(
        {
            "mode": "ACTIF",
            "ai_enabled": True,
            "ollama_model": "qwen2.5:3b",
            "cooldown_seconds": 0,
            "tts_enabled": True,
            "vocal_mode": "AUTONOME",
            "tts_delay_ms": 0,
            "max_pending_segments": 3,
        }
    )
    state = StateManager()
    events = EventManager(max_events=250)
    decision = DecisionEngine()
    ctrl = SessionController(cfg_mgr, state, events)
    ollama = OllamaClient("http://127.0.0.1:11434")
    mm = ModelManager(cfg_mgr, ollama)

    voices_dir = tmp_path / "voices"
    if with_voice:
        _create_dummy_voice(voices_dir)
    vm = VoiceManager(voices_dir=voices_dir)
    engine = PiperTTSEngine(voice_manager=vm, tools_dir=tmp_path / "tools")
    engine.get_backend_info = lambda: {  # type: ignore[method-assign]
        "available": True,
        "backend": "mock_piper",
        "python_piper_installed": True,
        "piper_binary_path": "",
        "model_loaded": False,
        "loaded_voice": "",
    }
    tts = TTSService(
        config_manager=cfg_mgr,
        state_manager=state,
        event_manager=events,
        voice_manager=vm,
        engine=engine,
    )
    ctrl.register_tts_hook(tts.interrupt)

    ped = PedagogicalService(
        config_manager=cfg_mgr,
        state_manager=state,
        event_manager=events,
        decision_engine=decision,
        session_controller=ctrl,
        ollama_client=ollama,
        model_manager=mm,
        tts_service=tts,
    )
    return cfg_mgr, state, events, ctrl, ollama, engine, tts, ped


def test_five_anti_echo_scenarios(tmp_path: Path):
    _, state, _, _, _, _, _, ped = _build_stack(tmp_path)
    neo_phrase = "PUT remplace toute la ressource tandis que PATCH modifie un seul champ."

    # 1. NÉO parle et le micro entend sa propre voix -> doit être filtré
    state.set_tts_status(tts_state="LECTURE", speaking=True)
    state.record_tts_spoken(neo_phrase)
    assert state.is_probable_tts_echo(neo_phrase) is True
    assert state.is_probable_tts_echo("tandis que PATCH modifie un seul champ") is True

    # 2. NÉO parle et un apprenant parle en même temps -> NON filtré
    assert (
        state.is_probable_tts_echo(
            "Mais du coup pour modifier juste le mot de passe on choisit quoi ?"
        )
        is False
    )

    # 3. NÉO parle et le formateur l'interrompt -> NON filtré
    assert state.is_probable_tts_echo("Stop Néo attends une seconde, je vais réexpliquer.") is False

    # 4. NÉO parle et une autre voix est détectée (sujet différent) -> NON filtré
    assert state.is_probable_tts_echo("Est-ce qu'on utilise aussi POST pour la création ?") is False

    # 5. NÉO termine sa phrase, puis une question est posée immédiatement en reprenant les mots -> NON filtré
    state.set_tts_status(tts_state="PRET", speaking=False)
    state.mark_tts_playback_ended()
    assert (
        state.is_probable_tts_echo(
            "Pourquoi PUT remplace toute la ressource et pas juste le champ modifié ?"
        )
        is False
    )
    assert state.is_probable_tts_echo("PUT remplace toute la ressource ?") is False

    # Vérification bout en bout via PedagogicalService sur un vrai écho
    state.set_tts_status(tts_state="LECTURE", speaking=True)
    res_echo = asyncio.run(
        ped.process_transcript(transcript=neo_phrase, speaker="Apprenant", is_simulated=False)
    )
    assert res_echo["intervened"] is False
    assert "Écho acoustique" in res_echo["decision"]


def test_stress_30min_listening_100_segments_errors_and_interruptions(tmp_path: Path):
    cfg_mgr, state, events, ctrl, ollama, engine, tts, ped = _build_stack(tmp_path)
    sqm = SegmentQueueManager(max_pending=3, temp_dir=tmp_path / "wavs")
    stt = FasterWhisperSTT(cache_dir=tmp_path / "hf")
    tx = TranscriptionService(cfg_mgr, state, events, sqm, stt)

    # 1. Simulation 30 minutes d'écoute (18 000 frames de 0,1 s = 1800 s) en VAD
    vad = VoiceActivityDetector(
        sample_rate=16000,
        energy_threshold=0.02,
        min_speech_seconds=0.4,
        silence_duration_seconds=0.5,
        max_segment_seconds=10.0,
    )
    silent_frame = _pcm(0, 1600)
    speech_frame = _pcm(3500, 1600)
    emitted_segments = 0
    for idx in range(18000):
        # toutes les 180 frames (18 s), 8 frames de parole puis silence
        is_talk = (idx % 180) < 8
        ev = vad.process_frame(speech_frame if is_talk else silent_frame)
        if ev.speech_ended and ev.segment_pcm:
            emitted_segments += 1
            sqm.enqueue(
                AudioSegment(
                    pcm_bytes=ev.segment_pcm,
                    sample_rate=16000,
                    channels=1,
                    duration_seconds=ev.duration_seconds,
                )
            )
    assert emitted_segments >= 90
    assert sqm.pending_count() <= 3
    assert len(vad._speech_buffer) == 0

    # 2. 100 segments consécutifs traités + suppression stricte des WAV temporaires
    sqm.clear()
    stt.transcribe_wav = lambda *_a, **_kw: TranscriptionResult(  # type: ignore[method-assign]
        text="Comment sécuriser une route API ?",
        is_empty=False,
        is_uncertain=False,
        avg_logprob=-0.25,
        duration_ms=15,
    )

    async def _run_100_segments() -> None:
        seg = AudioSegment(pcm_bytes=_pcm(1000, 800), sample_rate=16000, channels=1, duration_seconds=0.05)
        for _ in range(100):
            sqm.enqueue(seg)
            popped = sqm.dequeue(timeout=0.05)
            assert popped is not None
            r = await tx.transcribe_segment(popped)
            assert r.error is None

    asyncio.run(_run_100_segments())
    assert sqm.pending_count() == 0
    assert list((tmp_path / "wavs").glob("*.wav")) == []

    # 3. 20 appels LLM + 20 synthèses TTS + 10 interruptions mesurées en ms
    pcm_out = _pcm(400, 1600)
    engine.synthesize_pcm = lambda **_kw: SynthesizedAudio(  # type: ignore[method-assign]
        pcm_int16=pcm_out, sample_rate=16000, duration_ms=4
    )

    def fake_playback(_pcm: bytes, _sr: int):
        for _ in range(25):
            if tts.worker._cancel_event.is_set():
                return True, None
            time.sleep(0.01)
        return False, None

    tts.worker._play_pcm_chunked = fake_playback  # type: ignore[method-assign]

    async def _mock_ollama_ok(**_kw):
        return (
            json.dumps(
                {
                    "event_type": "QUESTION",
                    "analysis": "Question technique claire sur l'API.",
                    "should_intervene": True,
                    "intervention_type": "Exemple concret",
                    "is_off_topic": False,
                    "is_uncertain": False,
                    "confidence": 0.9,
                    "private_trainer_note": "Point clé à confirmer brièvement.",
                    "learner_response": "Utilisez un jeton d'authentification vérifié côté serveur à chaque requête.",
                }
            ),
            8,
        )

    ollama.generate_json = _mock_ollama_ok  # type: ignore[method-assign]

    async def _run_20_llm_tts() -> list[float]:
        interrupt_latencies_ms: list[float] = []
        for i in range(20):
            res = await ped.process_transcript(
                transcript=f"Question technique numéro {i} sur la validation HTTP ?",
                speaker="Apprenant",
                is_simulated=False,
            )
            assert res["intervened"] is True
            # Clear anti-repetition for synthetic loop variety
            state.recent_answers.clear()

            if i < 10:
                # Wait briefly for playback loop then measure interruption latency
                time.sleep(0.03)
                t0 = time.perf_counter()
                tts.interrupt("Interruption stress test")
                deadline = time.monotonic() + 1.0
                while tts.worker.is_busy() and time.monotonic() < deadline:
                    time.sleep(0.002)
                interrupt_latencies_ms.append((time.perf_counter() - t0) * 1000.0)
                assert tts.worker.is_busy() is False
            else:
                deadline = time.monotonic() + 1.0
                while tts.worker.is_busy() and time.monotonic() < deadline:
                    time.sleep(0.005)
        return interrupt_latencies_ms

    latencies = asyncio.run(_run_20_llm_tts())
    assert len(latencies) == 10
    assert max(latencies) < 100.0

    # 4. 10 changements de mode + 5 erreurs Ollama + 5 erreurs STT + 5 erreurs TTS
    modes_seq = ["OFF", "PASSIF", "SUR_DEMANDE", "ACTIF", "PASSIF", "ACTIF", "OFF", "ACTIF", "SUR_DEMANDE", "ACTIF"]
    for idx, m in enumerate(modes_seq):
        ctrl.on_behavior_mode_changed(m)
        cfg_mgr.update({"vocal_mode": ["SILENCIEUX", "ASSISTANT", "AUTONOME"][idx % 3]})

    async def _mock_ollama_fail(**_kw):
        raise RuntimeError("Connexion Ollama refusée (test stress)")

    ollama.generate_json = _mock_ollama_fail  # type: ignore[method-assign]
    for _ in range(5):
        res_err = asyncio.run(
            ped.process_transcript(
                transcript="Je ne comprends pas du tout cette erreur réseau.",
                speaker="Apprenant",
                is_simulated=False,
            )
        )
        assert "intervened" in res_err

    stt.transcribe_wav = lambda *_a, **_kw: TranscriptionResult(  # type: ignore[method-assign]
        text="", is_empty=True, is_uncertain=True, avg_logprob=-99.0, duration_ms=5, error="Erreur STT stress"
    )
    for _ in range(5):
        r_stt = asyncio.run(
            tx.transcribe_segment(AudioSegment(_pcm(100, 400), 16000, 1, 0.025))
        )
        assert r_stt.error == "Erreur STT stress"

    engine.synthesize_pcm = lambda **_kw: SynthesizedAudio(  # type: ignore[method-assign]
        pcm_int16=b"", sample_rate=22050, duration_ms=3, error="Erreur Piper stress"
    )
    cfg_mgr.update({"tts_enabled": True, "vocal_mode": "AUTONOME"})
    for _ in range(5):
        tts.test_voice("Test erreur TTS")
        deadline = time.monotonic() + 1.0
        while tts.worker.is_busy() and time.monotonic() < deadline:
            time.sleep(0.01)
    assert state.metrics.tts_errors_count >= 5

    # 5. Absence de micro + absence de voix + arrêt complet & redémarrage
    cap = AudioCapture()
    pipeline = AudioPipeline(cfg_mgr, state, cap, sqm)
    cap_ok = cap.start(device_index=999999)
    assert cap_ok is False

    _, _, _, _, _, _, tts_no_voice, _ = _build_stack(tmp_path / "novoice", with_voice=False)
    try:
        res_mv = tts_no_voice.test_voice("Test voix absente")
        assert res_mv["spoken"] is False
    finally:
        tts_no_voice.worker.stop_worker()

    ctrl.stop_session()
    pipeline.stop()
    tts.worker.stop_worker()
    assert state.session_active is False
    assert state.mic_active is False
    assert state.tts_speaking is False
    assert list((tmp_path / "wavs").glob("*.wav")) == []

    # Clean restart
    ctrl.start_session(enable_listening=False)
    assert state.session_active is True
    assert state.state == NeoState.EN_VEILLE
    ctrl.stop_session()


def test_all_12_pedagogical_scenarios(tmp_path: Path):
    cfg_mgr, state, events, ctrl, ollama, engine, tts, ped = _build_stack(tmp_path)
    engine.synthesize_pcm = lambda **_kw: SynthesizedAudio(  # type: ignore[method-assign]
        pcm_int16=_pcm(300, 400), sample_rate=16000, duration_ms=4
    )
    tts.worker._play_pcm_chunked = lambda _p, _sr: (False, None)  # type: ignore[method-assign]

    async def _run_scenarios() -> None:
        # 1. Question technique pertinente d'un apprenant
        ollama.generate_json = lambda **_kw: _async_json(  # type: ignore[method-assign]
            event_type="QUESTION",
            analysis="Question pertinente sur le code HTTP 422 vs 400.",
            should_intervene=True,
            intervention_type="Explication simplifiée",
            learner_response="Le code HTTP 400 signale une syntaxe illisible alors que le code 422 indique un email ou des champs métier invalides.",
            private_trainer_note="Préciser la nuance syntaxe vs validation métier.",
        )
        r1 = await ped.process_transcript(
            transcript="Pourquoi utiliser le code HTTP 422 plutôt que 400 sur un email invalide ?",
            is_simulated=False,
        )
        assert r1["intervened"] is True and r1["tts"]["spoken"] is True

        # 2. Incompréhension manifeste
        ollama.generate_json = lambda **_kw: _async_json(  # type: ignore[method-assign]
            event_type="INCOMPREHENSION",
            analysis="Blocage sur la notion d'idempotence.",
            should_intervene=True,
            intervention_type="Analogie",
            learner_response="L'idempotence veut dire qu'appuyer dix fois sur le bouton d'ascenseur produit le même résultat qu'une seule fois.",
            private_trainer_note="Apprenant bloqué sur l'idempotence : proposer l'analogie.",
        )
        r2 = await ped.process_transcript(
            transcript="Je ne comprends pas du tout ce que signifie l'idempotence.",
            is_simulated=False,
        )
        assert r2["intervened"] is True and r2["tts"]["spoken"] is True

        # 3. Confusion entre deux concepts
        ollama.generate_json = lambda **_kw: _async_json(  # type: ignore[method-assign]
            event_type="CONFUSION",
            analysis="Confusion entre PUT et PATCH.",
            should_intervene=True,
            intervention_type="Détection de confusion",
            learner_response="PUT remplace la fiche complète tandis que PATCH ne met à jour que le champ envoyé.",
            private_trainer_note="Clarifier PUT (complet) vs PATCH (partiel).",
        )
        r3 = await ped.process_transcript(
            transcript="Donc PUT et PATCH font exactement la même chose pour modifier un seul champ ?",
            is_simulated=False,
        )
        assert r3["intervened"] is True and r3["tts"]["spoken"] is True

        # 4. Question répétée (déjà posée et déjà expliquée)
        r4 = await ped.process_transcript(
            transcript="Pourquoi utilise-t-on le code HTTP 422 plutôt que 400 pour un email invalide ?",
            is_simulated=False,
        )
        assert r4["intervened"] is False

        # 5. Hors sujet
        ollama.generate_json = lambda **_kw: _async_json(  # type: ignore[method-assign]
            event_type="HORS_SUJET",
            analysis="Sujet logistique sans lien avec le cours.",
            should_intervene=False,
            is_off_topic=True,
            intervention_type="Aide au formateur",
            learner_response="",
            private_trainer_note="",
        )
        r5 = await ped.process_transcript(
            transcript="À quelle heure ferme la cafétéria cet après-midi ?",
            is_simulated=False,
        )
        assert r5["intervened"] is False

        # 6. Bruit / transcription vide
        r6 = await ped.process_transcript(transcript="   ", is_simulated=False)
        assert r6["intervened"] is False

        # 7. Demande explicite du formateur
        cfg_mgr.update({"mode": "SUR_DEMANDE", "vocal_mode": "ASSISTANT"})
        ollama.generate_json = lambda **_kw: _async_json(  # type: ignore[method-assign]
            event_type="DEMANDE_FORMATEUR",
            analysis="Sollicitation directe du formateur.",
            should_intervene=True,
            intervention_type="Exemple concret",
            learner_response="Avec PATCH /users/12, on n'envoie que l'email sans renvoyer le nom et l'adresse.",
            private_trainer_note="Exemple prêt à être lu ou diffusé.",
        )
        r7 = await ped.process_transcript(
            transcript="Néo, donne un exemple concret entre PUT et PATCH.",
            speaker="Formateur",
            explicit_trainer_request=True,
            is_simulated=False,
        )
        assert r7["intervened"] is True
        assert r7["tts"]["spoken"] is False  # Mode ASSISTANT -> attend bouton formateur

        # 8. Réponse incertaine (STT ou LLM incertain)
        cfg_mgr.update({"mode": "ACTIF", "vocal_mode": "AUTONOME"})
        r8 = await ped.process_transcript(
            transcript="Euh c'est le truc qui bloque quand on lance.",
            stt_uncertain=False,
            force_uncertain=True,
            is_simulated=False,
        )
        assert r8["intervened"] is False

        # 9. Mode OFF
        cfg_mgr.update({"mode": "OFF"})
        r9 = await ped.process_transcript(
            transcript="Je ne comprends pas comment fonctionne la validation des données.",
            is_simulated=False,
        )
        assert r9["intervened"] is False

        # 10. Mode PASSIF
        cfg_mgr.update({"mode": "PASSIF"})
        r10 = await ped.process_transcript(
            transcript="Comment fonctionne le routage FastAPI ?",
            is_simulated=False,
        )
        assert r10["intervened"] is False

        # 11. Mode SUR_DEMANDE sans sollicitation explicite
        cfg_mgr.update({"mode": "SUR_DEMANDE"})
        r11 = await ped.process_transcript(
            transcript="Pourquoi ce test unitaire échoue sans mock ?",
            is_simulated=False,
        )
        assert r11["intervened"] is False

        # 12. Interruption pendant parole de NÉO
        cfg_mgr.update({"mode": "ACTIF", "vocal_mode": "AUTONOME"})
        tts.worker._play_pcm_chunked = lambda _p, _sr: (  # type: ignore[method-assign]
            time.sleep(0.05) or (tts.worker._cancel_event.is_set(), None)
        )
        tts.speak_on_trainer_request("Explication interrompue par le formateur.")
        time.sleep(0.02)
        interrupted = tts.interrupt("Interruption scénario 12")
        assert interrupted is True

    asyncio.run(_run_scenarios())
    tts.worker.stop_worker()


async def _async_json(**overrides):
    payload = {
        "event_type": "ECHANGE_NORMAL",
        "analysis": "Analyse par défaut.",
        "should_intervene": False,
        "intervention_type": "Aide au formateur",
        "is_off_topic": False,
        "is_uncertain": False,
        "confidence": 0.88,
        "private_trainer_note": "",
        "learner_response": "",
    }
    payload.update(overrides)
    return json.dumps(payload), 10
