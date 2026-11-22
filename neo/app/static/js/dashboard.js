(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  let latestState = null;
  let activeView = "cockpit";
  let pollInFlight = false;
  let pollFollowUp = false;
  let pollTimer = null;

  async function api(url, method = "GET", body = null) {
    const opts = { method, headers: {} };
    if (body !== null) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || data.error || `Erreur HTTP ${res.status}`);
    }
    return data;
  }

  function showAlert(msg) {
    const el = $("global-alert");
    if (!msg) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    el.textContent = msg;
    el.classList.remove("hidden");
  }

  function switchView(viewName) {
    activeView = viewName;
    document.querySelectorAll(".nav-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.view === viewName);
    });
    document.querySelectorAll(".view").forEach((sec) => {
      sec.classList.toggle("active", sec.id === `view-${viewName}`);
    });
    if (viewName === "audio") refreshAudioView();
    if (viewName === "voice") refreshVoiceView();
    if (viewName === "models") refreshModelsView();
    if (viewName === "diagnostics") runDiagnosticsView(false);
    if (viewName === "settings" || viewName === "session") loadSettingsIntoForms();
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function renderState(state) {
    latestState = state;

    $("neo-state-badge").textContent = state.neo_state;
    $("quick-mode-select").value = state.mode;
    if ($("quick-vocal-select")) {
      $("quick-vocal-select").value = state.vocal_mode || "ASSISTANT";
    }
    $("cooldown-label").textContent = `Cooldown : ${state.cooldown_remaining} s`;

    const isListeningState =
      state.neo_state === "ÉCOUTE" || state.neo_state === "PAROLE DÉTECTÉE";
    $("listening-wave").classList.toggle("hidden", !isListeningState);
    $("mic-privacy-banner").classList.toggle("hidden", !state.mic_active);

    $("btn-toggle-listen").textContent = state.listening_enabled ? "Écoute : On" : "Écoute : Off";
    $("btn-toggle-neo").textContent =
      state.mode === "OFF" ? "Activer NÉO" : "Désactiver NÉO";

    const tts = state.tts || {};
    const stopVoiceBtn = $("btn-stop-voice");
    if (stopVoiceBtn) {
      stopVoiceBtn.classList.toggle("is-speaking", Boolean(tts.speaking));
    }

    // Warning / Errors
    const alertMsg = state.last_error || state.config_warning || "";
    showAlert(alertMsg);

    // System indicators
    const ol = state.ollama || {};
    $("ind-ollama").textContent = ol.connected ? "Connecté" : "Déconnecté";
    $("ind-ollama").style.color = ol.connected ? "#10b981" : "#f43f5e";
    $("ind-model").textContent = ol.selected_model || "Aucun sélectionné";

    const au = state.audio || {};
    $("ind-mic").textContent = state.mic_active
      ? `Actif (${au.selected_device_name || "Défaut"})`
      : "Inactif";
    $("ind-audio-bar").style.width = `${Math.min(100, Math.round((state.audio_level || 0) * 350))}%`;

    const stt = state.stt || {};
    $("ind-stt").textContent = `${stt.selected_model || "small"} (${
      stt.selected_installed ? "local" : "non installé"
    })`;

    const sys = state.system || {};
    const cpuTxt = sys.cpu_percent !== null && sys.cpu_percent !== undefined ? `${sys.cpu_percent}%` : "—";
    const ramTxt =
      sys.ram_available_mb !== null && sys.ram_available_mb !== undefined
        ? `${Math.round(sys.ram_available_mb / 102.4) / 10} Go libres`
        : "—";
    $("ind-sys").textContent = `${cpuTxt} / ${ramTxt}`;

    const met = state.metrics || {};
    $("ind-latency").textContent = `${met.last_transcription_ms || 0} ms / ${met.last_llm_ms || 0} ms`;

    const indTts = $("ind-tts");
    if (indTts) {
      const ttsLabel = tts.tts_enabled
        ? `${tts.tts_state || "PRÊT"} (${tts.vocal_mode || state.vocal_mode || "ASSISTANT"})`
        : "INACTIF";
      indTts.textContent = ttsLabel;
    }

    // Session Context Line
    const ctx = state.training_context || {};
    $("cockpit-session-title").textContent = ctx.title || "Session de formation";
    $("cockpit-context-summary").textContent = [
      ctx.subject ? `Sujet : ${ctx.subject}` : "Sujet non défini",
      `Niveau : ${ctx.learner_level || "Intermédiaire"}`,
      `Mode : ${state.mode}`,
    ].join(" · ");

    // Cockpit stream (transcripts / decisions)
    const streamEl = $("cockpit-stream");
    const items = (state.history || []).filter(
      (h) => h.transcript || h.kind === "decision" || h.kind === "error"
    );
    if (items.length === 0) {
      streamEl.innerHTML = `<div class="empty-box">Aucun échange enregistré pour cette session.</div>`;
    } else {
      streamEl.innerHTML = items
        .slice(0, 25)
        .map(
          (item) => `
          <div class="stream-item">
            <div class="stream-meta">
              <span class="mono">${escapeHtml(item.timestamp)}</span>
              <span>·</span>
              <strong>${escapeHtml(item.event_type || item.kind)}</strong>
              ${item.is_simulated ? "<span>· SIMULATION</span>" : ""}
            </div>
            ${
              item.transcript
                ? `<div class="stream-text">${escapeHtml(item.transcript)}</div>`
                : ""
            }
            ${
              item.decision
                ? `<div class="small muted">${escapeHtml(item.decision)}</div>`
                : ""
            }
            ${
              item.error
                ? `<div class="small" style="color:#fda4af">${escapeHtml(item.error)}</div>`
                : ""
            }
          </div>`
        )
        .join("");
    }

    // Active Proposal
    renderProposal(state.active_proposal, state.last_silence_reason);

    // Learner Broadcasts
    const bList = $("learner-broadcast-list");
    const pub = state.published_to_learners || [];
    if (pub.length === 0) {
      bList.innerHTML = `<div class="muted small">Aucune réponse diffusée aux apprenants.</div>`;
    } else {
      bList.innerHTML = pub
        .map(
          (p, idx) => `
          <div class="broadcast-item">
            <div class="small muted mono">${escapeHtml(p.time)} · ${escapeHtml(p.type)}${
            p.is_simulated ? " · SIMULATION" : ""
          }</div>
            <div style="margin-top:4px">${escapeHtml(p.text)}</div>
            <div style="margin-top:6px">
              <button class="btn btn-sm" data-broadcast-speak="${idx}" type="button">Prononcer</button>
            </div>
          </div>`
        )
        .join("");

      bList.querySelectorAll("[data-broadcast-speak]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const item = pub[Number(btn.dataset.broadcastSpeak)];
          if (!item || !item.text) return;
          try {
            const res = await api("/api/tts/speak", "POST", { text: item.text });
            if (!res.spoken && res.reason) showAlert(res.reason);
            await pollState();
          } catch (err) {
            showAlert(err.message);
          }
        });
      });
    }

    // Simulation cards (render once or keep updated)
    renderSimulationScenarios(state.simulation_scenarios || []);

    // History table
    renderHistory(state.history || []);
  }

  function renderProposal(prop, silenceReason) {
    const container = $("proposal-container");
    const meta = $("proposal-meta");
    if (!prop) {
      meta.textContent = "Silencieux";
      container.innerHTML = `<div class="empty-box">${escapeHtml(
        silenceReason ||
          "NÉO reste silencieux tant qu'aucun besoin pédagogique pertinent n'est détecté."
      )}</div>`;
      return;
    }

    meta.textContent = `${prop.intervention_type} · Confiance ${Math.round(
      (prop.confidence || 0) * 100
    )}% · ${prop.processing_ms} ms`;

    container.innerHTML = `
      <div class="proposal-card">
        <div class="small muted">
          <span class="mono">${escapeHtml(prop.created_at)}</span> ·
          <strong>${escapeHtml(prop.event_type)}</strong>
          ${prop.is_simulated ? " · SIMULATION" : ""}
        </div>
        <div class="small"><strong>Phrase d'origine :</strong> « ${escapeHtml(prop.transcript)} »</div>
        <div class="small muted"><strong>Analyse :</strong> ${escapeHtml(prop.analysis)}</div>
        <div class="small muted"><strong>Décision :</strong> ${escapeHtml(prop.decision)}</div>

        ${
          prop.private_trainer_note
            ? `<div class="proposal-block">
                <div class="proposal-block-title">Suggestion privée (formateur)</div>
                <div>${escapeHtml(prop.private_trainer_note)}</div>
              </div>`
            : ""
        }

        ${
          prop.learner_response
            ? `<div class="proposal-block">
                <div class="proposal-block-title">Réponse proposée (apprenants)</div>
                <div>${escapeHtml(prop.learner_response)}</div>
              </div>`
            : ""
        }

        <div class="proposal-actions">
          <button class="btn btn-primary btn-sm" data-prop-action="accept" type="button">Accepter</button>
          <button class="btn btn-sm" data-prop-action="ignore" type="button">Ignorer</button>
          <button class="btn btn-sm" data-prop-action="reformulate" type="button">Reformuler</button>
          <button class="btn btn-sm" data-prop-action="develop" type="button">Développer</button>
          <button class="btn btn-sm" data-prop-copy="1" type="button">Copier</button>
          ${
            prop.learner_response || prop.private_trainer_note
              ? `<button class="btn btn-sm" data-prop-speak="1" type="button">Faire prononcer par NÉO</button>`
              : ""
          }
          ${
            prop.learner_response
              ? `<button class="btn btn-sm" data-prop-action="publish" type="button">Diffuser aux apprenants</button>`
              : ""
          }
        </div>
      </div>
    `;

    container.querySelectorAll("[data-prop-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/session/proposals/${prop.id}/action`, "POST", {
            action: btn.dataset.propAction,
          });
          await pollState();
        } catch (err) {
          showAlert(err.message);
        }
      });
    });

    const speakBtn = container.querySelector("[data-prop-speak]");
    if (speakBtn) {
      speakBtn.addEventListener("click", async () => {
        const txt = prop.learner_response || prop.private_trainer_note || "";
        try {
          const res = await api("/api/tts/speak", "POST", { text: txt });
          if (!res.spoken && res.reason) {
            showAlert(res.reason);
          }
          await pollState();
        } catch (err) {
          showAlert(err.message);
        }
      });
    }

    const copyBtn = container.querySelector("[data-prop-copy]");
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        const txt = prop.learner_response || prop.private_trainer_note || "";
        try {
          await navigator.clipboard.writeText(txt);
          copyBtn.textContent = "Copié";
          setTimeout(() => (copyBtn.textContent = "Copier"), 1500);
        } catch {
          showAlert("Copie dans le presse-papiers refusée par le navigateur.");
        }
      });
    }
  }

  let scenariosRendered = false;
  function renderSimulationScenarios(scenarios) {
    if (scenariosRendered || scenarios.length === 0) return;
    scenariosRendered = true;
    const grid = $("simulation-grid");
    grid.innerHTML = scenarios
      .map(
        (sc) => `
      <div class="sim-card">
        <div>
          <div style="font-weight:600;margin-bottom:4px">${escapeHtml(sc.label)}</div>
          <div class="small muted">« ${escapeHtml(sc.transcript.trim() || "(vide)")} »</div>
        </div>
        <button class="btn btn-sm" data-sim-id="${escapeHtml(sc.id)}" type="button">Exécuter ce scénario</button>
      </div>`
      )
      .join("");

    grid.querySelectorAll("[data-sim-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await api("/api/session/simulate", "POST", { scenario_id: btn.dataset.simId });
          await pollState();
          switchView("cockpit");
        } catch (err) {
          showAlert(err.message);
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  function renderHistory(history) {
    const tbody = $("history-table-body");
    if (history.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted">Historique vide.</td></tr>`;
      return;
    }
    tbody.innerHTML = history
      .map(
        (row) => `
      <tr>
        <td class="mono">${escapeHtml(row.timestamp)}</td>
        <td>${row.is_simulated ? "SIMULATION" : "DIRECT"}</td>
        <td>${escapeHtml(row.event_type || row.kind)}</td>
        <td>${escapeHtml(row.transcript)}</td>
        <td>${escapeHtml(row.analysis)}</td>
        <td>${escapeHtml(row.decision || row.error)}</td>
        <td>${escapeHtml(row.proposal)}</td>
        <td class="mono">${row.transcription_ms} / ${row.llm_ms} ms</td>
      </tr>`
      )
      .join("");
  }

  async function pollState(isBackground = false) {
    const background = isBackground === true;
    if (background && document.hidden) {
      return;
    }
    if (pollInFlight) {
      if (!background) {
        pollFollowUp = true;
      }
      return;
    }
    pollInFlight = true;
    try {
      const state = await api("/api/dashboard/state");
      renderState(state);
    } catch (err) {
      showAlert(err.message);
    } finally {
      pollInFlight = false;
      if (pollFollowUp) {
        pollFollowUp = false;
        pollState(false);
      }
    }
  }

  function startPolling() {
    if (pollTimer !== null) {
      return;
    }
    pollTimer = setInterval(() => {
      pollState(true);
    }, 1200);
  }

  function stopPolling() {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function refreshAudioView() {
    try {
      const [devData, sttData, settingsData] = await Promise.all([
        api("/api/audio/devices"),
        api("/api/audio/stt-models"),
        api("/api/settings"),
      ]);
      const sel = $("audio-device-select");
      if (devData.devices.length === 0) {
        sel.innerHTML = `<option value="">${escapeHtml(
          devData.error || "Aucun microphone détecté"
        )}</option>`;
      } else {
        sel.innerHTML =
          `<option value="">Périphérique système par défaut</option>` +
          devData.devices
            .map(
              (d) =>
                `<option value="${d.index}" ${
                  devData.selected_device_index === d.index ? "selected" : ""
                }>${escapeHtml(d.name)} (${d.default_samplerate} Hz)</option>`
            )
            .join("");
      }

      $("stt-model-select").value = sttData.selected_model;
      $("stt-installed-list").textContent =
        "Modèles installés localement : " +
        (sttData.installed.length > 0 ? sttData.installed.join(", ") : "aucun");

      const cfg = settingsData.config;
      $("vad-threshold").value = cfg.vad_energy_threshold;
      $("vad-min-speech").value = cfg.vad_min_speech_seconds;
      $("vad-silence").value = cfg.vad_silence_duration_seconds;
      $("vad-max-seg").value = cfg.vad_max_segment_seconds;
    } catch (err) {
      showAlert(err.message);
    }
  }

  async function refreshModelsView() {
    try {
      const [data, settingsData] = await Promise.all([api("/api/models"), api("/api/settings")]);
      const cfg = settingsData.config;

      $("ollama-url-input").value = cfg.ollama_url;
      $("llm-temp").value = cfg.llm_temperature;
      $("llm-timeout").value = cfg.llm_timeout_seconds;
      $("llm-max-sentences").value = cfg.max_response_sentences;
      $("ai-enabled-checkbox").checked = Boolean(cfg.ai_enabled);

      $("ollama-status-line").textContent = data.connected
        ? `Ollama connecté sur ${data.ollama_url} — ${data.models.length} modèle(s) détecté(s).`
        : data.error || "Ollama déconnecté.";

      const sel = $("ollama-model-select");
      if (data.models.length === 0) {
        sel.innerHTML = `<option value="">Aucun modèle Ollama installé</option>`;
        $("models-table-body").innerHTML = `<tr><td colspan="4" class="muted">${escapeHtml(
          data.error || "Aucun modèle présent dans Ollama."
        )}</td></tr>`;
      } else {
        sel.innerHTML = data.models
          .map(
            (m) =>
              `<option value="${escapeHtml(m.name)}" ${
                data.selected_model === m.name ? "selected" : ""
              }>${escapeHtml(m.name)} (${escapeHtml(m.size_label)})</option>`
          )
          .join("");
        $("models-table-body").innerHTML = data.models
          .map(
            (m) => `
          <tr>
            <td class="mono">${escapeHtml(m.name)}</td>
            <td class="mono">${escapeHtml(m.size_label)}</td>
            <td>${escapeHtml(m.parameter_size || "—")}</td>
            <td>${escapeHtml(m.quantization || "—")}</td>
          </tr>`
          )
          .join("");
      }
    } catch (err) {
      showAlert(err.message);
    }
  }

  async function refreshVoiceView() {
    try {
      const [ttsData, settingsData] = await Promise.all([
        api("/api/tts/status"),
        api("/api/settings"),
      ]);
      const cfg = settingsData.config || {};

      $("tts-engine-state").textContent = ttsData.tts_state || "INACTIF";
      $("tts-enabled-checkbox").checked = Boolean(cfg.tts_enabled);
      $("tts-vocal-mode-select").value = cfg.vocal_mode || "ASSISTANT";
      $("tts-speed-range").value = cfg.tts_speed ?? 1.0;
      $("tts-speed-val").textContent = Number($("tts-speed-range").value).toFixed(2);
      $("tts-volume-range").value = cfg.tts_volume ?? 0.9;
      $("tts-volume-val").textContent = String(Math.round(Number($("tts-volume-range").value) * 100));
      $("tts-delay-ms").value = cfg.tts_delay_ms ?? 500;
      $("tts-max-chars").value = cfg.tts_max_spoken_chars ?? 380;
      $("tts-error-policy").value = cfg.tts_error_policy || "silent_fallback";
      $("tts-auto-unload").value = cfg.tts_auto_unload_seconds ?? 120;

      const backend = ttsData.backend || {};
      const backendTxt = backend.available
        ? `Moteur local Piper prêt (${backend.backend})`
        : "Moteur Piper absent (installez piper-tts ou placez piper.exe dans neo/tools/piper/)";
      const voiceTxt = ttsData.selected_voice_installed
        ? `Voix '${ttsData.selected_voice}' installée et valide.`
        : ttsData.selected_voice_error || `Voix '${ttsData.selected_voice}' non installée.`;
      $("tts-status-summary").textContent = `${backendTxt} · ${voiceTxt}`;

      const voices = ttsData.voices || [];
      const sel = $("tts-voice-select");
      sel.innerHTML = voices
        .map(
          (v) =>
            `<option value="${escapeHtml(v.voice_id)}" ${
              v.voice_id === ttsData.selected_voice ? "selected" : ""
            }>${escapeHtml(v.label)} ${v.valid ? "[Installée]" : "[Absente]"}</option>`
        )
        .join("");

      $("voices-table-body").innerHTML = voices
        .map(
          (v) => `
          <tr>
            <td>
              <div class="mono">${escapeHtml(v.voice_id)}</div>
              <div class="small muted">${escapeHtml(v.description || "")}</div>
            </td>
            <td style="color:${v.valid ? "#10b981" : v.installed ? "#f43f5e" : "#94a3b8"}">${
            v.valid ? "Installée" : v.installed ? "Invalide" : "Non installée"
          }</td>
            <td class="mono">${escapeHtml(v.size_label || "—")}</td>
            <td class="small">${escapeHtml(v.license || "—")}</td>
          </tr>`
        )
        .join("");
    } catch (err) {
      showAlert(err.message);
    }
  }

  async function loadSettingsIntoForms() {
    try {
      const { config: cfg } = await api("/api/settings");
      const ctx = cfg.training_context || {};
      $("ctx-title").value = ctx.title || "";
      $("ctx-subject").value = ctx.subject || "";
      $("ctx-level").value = ctx.learner_level || "Intermédiaire";
      $("ctx-objectives").value = ctx.objectives || "";
      $("ctx-instructions").value = ctx.custom_instructions || "";

      $("cfg-cooldown").value = cfg.cooldown_seconds;
      $("cfg-max-chars").value = cfg.max_response_chars;
      $("cfg-stt-timeout").value = cfg.stt_timeout_seconds;
      $("cfg-keep-wav").checked = Boolean(cfg.privacy && cfg.privacy.keep_audio_diagnostic);
      $("cfg-persist-history").checked = Boolean(
        cfg.privacy && cfg.privacy.persist_session_history
      );
    } catch (err) {
      showAlert(err.message);
    }
  }

  async function runDiagnosticsView(runCheck = true) {
    try {
      const data = runCheck
        ? await api("/api/diagnostics/run", "POST")
        : { checks: [], snapshot: await api("/api/diagnostics") };

      const checksEl = $("diag-checks");
      if (data.checks && data.checks.length > 0) {
        checksEl.innerHTML = data.checks
          .map(
            (c) => `
          <div class="diag-item">
            <div style="font-weight:600;color:${c.ok ? "#10b981" : "#f43f5e"}">${
              c.ok ? "OK" : "ALERTE"
            } · ${escapeHtml(c.name)}</div>
            <div class="small muted" style="margin-top:4px">${escapeHtml(c.detail)}</div>
          </div>`
          )
          .join("");
      } else {
        checksEl.innerHTML = `<div class="muted small">Cliquez sur « Lancer le diagnostic global » pour vérifier chaque composant sans télécharger de modèle.</div>`;
      }
      $("diag-json").textContent = JSON.stringify(data.snapshot, null, 2);
    } catch (err) {
      showAlert(err.message);
    }
  }

  function bindEvents() {
    document.querySelectorAll(".nav-item").forEach((btn) => {
      btn.addEventListener("click", () => switchView(btn.dataset.view));
    });

    $("btn-start").addEventListener("click", () =>
      api("/api/session/start", "POST").then(pollState).catch((e) => showAlert(e.message))
    );
    $("btn-pause").addEventListener("click", () =>
      api("/api/session/pause", "POST").then(pollState).catch((e) => showAlert(e.message))
    );
    $("btn-resume").addEventListener("click", () =>
      api("/api/session/resume", "POST").then(pollState).catch((e) => showAlert(e.message))
    );
    $("btn-stop").addEventListener("click", () =>
      api("/api/session/stop", "POST").then(pollState).catch((e) => showAlert(e.message))
    );
    $("btn-interrupt").addEventListener("click", () =>
      api("/api/session/interrupt", "POST").then(pollState).catch((e) => showAlert(e.message))
    );
    $("btn-stop-voice").addEventListener("click", () =>
      api("/api/tts/stop", "POST").then(pollState).catch((e) => showAlert(e.message))
    );
    $("btn-toggle-listen").addEventListener("click", () => {
      const next = !(latestState && latestState.listening_enabled);
      api("/api/session/toggle-listen", "POST", { enabled: next })
        .then(pollState)
        .catch((e) => showAlert(e.message));
    });
    $("btn-toggle-neo").addEventListener("click", () => {
      const nextEnabled = latestState ? latestState.mode === "OFF" : true;
      api("/api/session/toggle-neo", "POST", { enabled: nextEnabled })
        .then(pollState)
        .catch((e) => showAlert(e.message));
    });

    $("quick-mode-select").addEventListener("change", (e) => {
      api("/api/session/mode", "POST", { mode: e.target.value })
        .then(pollState)
        .catch((err) => showAlert(err.message));
    });
    if ($("quick-vocal-select")) {
      $("quick-vocal-select").addEventListener("change", (e) => {
        api("/api/tts/mode", "POST", { vocal_mode: e.target.value })
          .then(pollState)
          .catch((err) => showAlert(err.message));
      });
    }

    $("trainer-command-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = $("trainer-command-input");
      const cmd = input.value.trim();
      if (!cmd) return;
      input.value = "";
      try {
        await api("/api/session/command", "POST", { command: cmd });
        await pollState();
      } catch (err) {
        showAlert(err.message);
      }
    });

    document.querySelectorAll(".quick-cmd").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api("/api/session/command", "POST", {
            command: btn.dataset.cmd,
            intervention_hint: btn.dataset.hint,
          });
          await pollState();
        } catch (err) {
          showAlert(err.message);
        }
      });
    });

    // Session Context Form
    $("session-context-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api("/api/settings", "PUT", {
          training_context: {
            title: $("ctx-title").value.trim() || "Session de formation",
            subject: $("ctx-subject").value.trim(),
            learner_level: $("ctx-level").value,
            objectives: $("ctx-objectives").value.trim(),
            custom_instructions: $("ctx-instructions").value.trim(),
          },
        });
        await pollState();
        switchView("cockpit");
      } catch (err) {
        showAlert(err.message);
      }
    });

    // Audio View
    $("btn-refresh-mics").addEventListener("click", refreshAudioView);
    $("audio-device-select").addEventListener("change", async (e) => {
      const val = e.target.value;
      const label = e.target.options[e.target.selectedIndex]?.text || "";
      try {
        await api("/api/audio/select", "POST", {
          device_index: val === "" ? null : Number(val),
          device_name: val === "" ? "" : label,
        });
        await pollState();
      } catch (err) {
        showAlert(err.message);
      }
    });
    $("btn-test-mic").addEventListener("click", async () => {
      $("mic-test-result").textContent = "Test en cours…";
      try {
        const res = await api("/api/audio/test", "POST");
        $("mic-test-result").textContent = res.ok
          ? `OK · Pic ${Math.round(res.peak_level * 100)}%`
          : res.error;
      } catch (err) {
        $("mic-test-result").textContent = err.message;
      }
    });
    $("btn-save-vad").addEventListener("click", async () => {
      try {
        await api("/api/settings", "PUT", {
          vad_energy_threshold: Number($("vad-threshold").value),
          vad_min_speech_seconds: Number($("vad-min-speech").value),
          vad_silence_duration_seconds: Number($("vad-silence").value),
          vad_max_segment_seconds: Number($("vad-max-seg").value),
        });
        await pollState();
      } catch (err) {
        showAlert(err.message);
      }
    });
    $("btn-save-stt").addEventListener("click", async () => {
      try {
        const res = await api("/api/audio/stt-models/select", "POST", {
          model_name: $("stt-model-select").value,
        });
        $("stt-action-status").textContent = res.installed
          ? `Modèle '${res.selected_model}' sélectionné et prêt.`
          : `Modèle '${res.selected_model}' sélectionné (non encore téléchargé).`;
        await pollState();
      } catch (err) {
        showAlert(err.message);
      }
    });
    $("btn-download-stt").addEventListener("click", async () => {
      $("stt-action-status").textContent = "Téléchargement explicite du modèle Faster-Whisper…";
      try {
        const res = await api("/api/audio/stt-models/download", "POST", {
          model_name: $("stt-model-select").value,
        });
        $("stt-action-status").textContent = res.message;
        await refreshAudioView();
        await pollState();
      } catch (err) {
        $("stt-action-status").textContent = err.message;
      }
    });

    // Models View
    $("btn-refresh-models").addEventListener("click", refreshModelsView);
    $("btn-save-model-settings").addEventListener("click", async () => {
      try {
        await api("/api/settings", "PUT", {
          ollama_url: $("ollama-url-input").value.trim(),
          ollama_model: $("ollama-model-select").value,
          llm_temperature: Number($("llm-temp").value),
          llm_timeout_seconds: Number($("llm-timeout").value),
          max_response_sentences: Number($("llm-max-sentences").value),
          ai_enabled: $("ai-enabled-checkbox").checked,
        });
        await refreshModelsView();
        await pollState();
      } catch (err) {
        showAlert(err.message);
      }
    });
    $("btn-test-model").addEventListener("click", async () => {
      $("model-test-result").textContent = "Test en cours…";
      try {
        const res = await api("/api/models/test", "POST", {
          model_name: $("ollama-model-select").value,
        });
        $("model-test-result").textContent = res.ok
          ? `OK (${res.latency_ms} ms) : ${res.reply}`
          : `Échec : ${res.error}`;
      } catch (err) {
        $("model-test-result").textContent = err.message;
      }
    });

    // Voice View (Voix de NÉO)
    $("tts-speed-range").addEventListener("input", () => {
      $("tts-speed-val").textContent = Number($("tts-speed-range").value).toFixed(2);
    });
    $("tts-volume-range").addEventListener("input", () => {
      $("tts-volume-val").textContent = String(Math.round(Number($("tts-volume-range").value) * 100));
    });
    $("btn-refresh-voices").addEventListener("click", refreshVoiceView);
    $("tts-voice-select").addEventListener("change", async (e) => {
      try {
        const res = await api("/api/tts/voices/select", "POST", { voice_id: e.target.value });
        $("tts-action-status").textContent = res.installed
          ? `Voix '${res.selected_voice}' prête.`
          : res.error || `Voix '${res.selected_voice}' non installée.`;
        await refreshVoiceView();
        await pollState();
      } catch (err) {
        showAlert(err.message);
      }
    });
    $("btn-save-tts").addEventListener("click", async () => {
      try {
        await api("/api/settings", "PUT", {
          tts_enabled: $("tts-enabled-checkbox").checked,
          vocal_mode: $("tts-vocal-mode-select").value,
          tts_voice: $("tts-voice-select").value,
          tts_speed: Number($("tts-speed-range").value),
          tts_volume: Number($("tts-volume-range").value),
          tts_delay_ms: Number($("tts-delay-ms").value),
          tts_max_spoken_chars: Number($("tts-max-chars").value),
          tts_error_policy: $("tts-error-policy").value,
          tts_auto_unload_seconds: Number($("tts-auto-unload").value),
        });
        $("tts-action-status").textContent = "Paramètres vocaux sauvegardés.";
        await refreshVoiceView();
        await pollState();
      } catch (err) {
        showAlert(err.message);
      }
    });
    $("btn-test-voice").addEventListener("click", async () => {
      $("tts-action-status").textContent = "Synthèse vocale de test en cours…";
      try {
        const res = await api("/api/tts/test", "POST", {
          text: $("tts-test-text").value.trim() || null,
        });
        $("tts-action-status").textContent = res.spoken
          ? `Lecture lancée (${res.voice}).`
          : res.reason || res.error || "Impossible de tester la voix.";
        await pollState();
      } catch (err) {
        $("tts-action-status").textContent = err.message;
      }
    });
    $("btn-voice-panel-stop").addEventListener("click", async () => {
      await api("/api/tts/stop", "POST");
      $("tts-action-status").textContent = "Voix interrompue.";
      await pollState();
    });
    $("btn-unload-tts").addEventListener("click", async () => {
      await api("/api/tts/unload", "POST");
      $("tts-action-status").textContent = "Modèle vocal déchargé de la RAM.";
      await refreshVoiceView();
    });
    $("btn-download-voice").addEventListener("click", async () => {
      const vid = $("tts-voice-select").value;
      $("tts-action-status").textContent = `Téléchargement explicite de '${vid}' en cours…`;
      try {
        const res = await api("/api/tts/voices/download", "POST", { voice_id: vid });
        $("tts-action-status").textContent = res.message;
        await refreshVoiceView();
        await pollState();
      } catch (err) {
        $("tts-action-status").textContent = err.message;
      }
    });
    $("btn-delete-voice").addEventListener("click", async () => {
      const vid = $("tts-voice-select").value;
      try {
        const res = await api(`/api/tts/voices/${encodeURIComponent(vid)}`, "DELETE");
        $("tts-action-status").textContent = res.message;
        await refreshVoiceView();
        await pollState();
      } catch (err) {
        $("tts-action-status").textContent = err.message;
      }
    });

    // History & Diagnostics & Settings
    $("btn-clear-history").addEventListener("click", () =>
      api("/api/session/history", "DELETE").then(pollState).catch((e) => showAlert(e.message))
    );
    $("btn-run-diag").addEventListener("click", () => runDiagnosticsView(true));
    $("settings-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api("/api/settings", "PUT", {
          cooldown_seconds: Number($("cfg-cooldown").value),
          max_response_chars: Number($("cfg-max-chars").value),
          stt_timeout_seconds: Number($("cfg-stt-timeout").value),
          privacy: {
            keep_audio_diagnostic: $("cfg-keep-wav").checked,
            persist_session_history: $("cfg-persist-history").checked,
          },
        });
        await pollState();
      } catch (err) {
        showAlert(err.message);
      }
    });
    $("btn-reset-settings").addEventListener("click", async () => {
      try {
        await api("/api/settings/reset", "POST");
        await loadSettingsIntoForms();
        await pollState();
      } catch (err) {
        showAlert(err.message);
      }
    });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopPolling();
    } else {
      pollState(false);
      startPolling();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    if (!document.hidden) {
      pollState(false);
      startPolling();
    }
  });
})();
