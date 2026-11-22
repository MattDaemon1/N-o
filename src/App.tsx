import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Clock, RotateCcw, Users, Volume2 } from 'lucide-react';
import { ArchitectureView } from './components/ArchitectureView';
import { ExchangeStream } from './components/ExchangeStream';
import { InterventionZone } from './components/InterventionZone';
import { LearnerScreenView } from './components/LearnerScreenView';
import { ListeningIndicator } from './components/ListeningIndicator';
import { SessionConfigView } from './components/SessionConfigView';
import { SupervisionJournalView } from './components/SupervisionJournalView';
import {
  listAudioInputDevices,
  LiveMicrophoneAdapter,
  NeoVoicePlayer,
  type AudioDeviceOption,
  type CaptureMode,
} from './services/neo/audioInputAdapter';
import {
  detectLocalContextInsights,
  evaluateInterventionGate,
  updateMemoryWithProposal,
} from './services/neo/decisionEngine';
import {
  analyzeUtteranceWithGemini,
  checkNeoHealth,
  sendTrainerCommandWithGemini,
  synthesizeSpeechWithGemini,
  transcribeAudioWithGemini,
} from './services/neo/llmEngine';
import { SESSION_TEMPLATES } from './services/neo/templates';
import type {
  EventLogEntry,
  InputOrigin,
  NeoMode,
  NeoProposal,
  NeoState,
  NeoVoiceName,
  ScreenBroadcastItem,
  SessionConfig,
  SessionMemory,
  SessionMetrics,
  SpeakerRole,
  TranscriptExchange,
} from './services/neo/types';

type WorkspaceTab = 'cockpit' | 'session' | 'journal' | 'ecran' | 'architecture';

const MODES: Array<{ id: NeoMode; desc: string }> = [
  { id: 'ACTIF', desc: 'Analyse et propose spontanément' },
  { id: 'PASSIF', desc: 'Analyse silencieuse sans proposition' },
  { id: 'SUR DEMANDE', desc: 'Répond uniquement sur sollicitation' },
  { id: 'OFF', desc: 'Analyse et interventions coupées' },
];

const VOICES: Array<{ id: NeoVoiceName; label: string }> = [
  { id: 'Kore', label: 'Kore (posée)' },
  { id: 'Charon', label: 'Charon (grave)' },
  { id: 'Zephyr', label: 'Zephyr (claire)' },
  { id: 'Puck', label: 'Puck (dynamique)' },
  { id: 'Fenrir', label: 'Fenrir (ferme)' },
];

const INITIAL_MEMORY: SessionMemory = {
  askedQuestions: [],
  resolvedTopics: [],
  persistentDifficulties: [],
  confusedPairs: [],
  previousInterventions: [],
};

function formatTimeNow(): string {
  return new Date().toLocaleTimeString('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatDurationMMSS(totalSec: number): string {
  const hrs = Math.floor(totalSec / 3600);
  const mins = Math.floor((totalSec % 3600) / 60);
  const secs = totalSec % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return hrs > 0 ? `${pad(hrs)}:${pad(mins)}:${pad(secs)}` : `${pad(mins)}:${pad(secs)}`;
}

function makeId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('cockpit');
  const [sessionRunning, setSessionRunning] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [mode, setMode] = useState<NeoMode>('ACTIF');
  const [neoState, setNeoState] = useState<NeoState>('En veille');

  const [sessionConfig, setSessionConfig] = useState<SessionConfig>(
    () => SESSION_TEMPLATES[0].config,
  );
  const [exchanges, setExchanges] = useState<TranscriptExchange[]>([]);
  const [activeProposal, setActiveProposal] = useState<NeoProposal | null>(null);
  const [lastSilenceReason, setLastSilenceReason] = useState<string | null>(null);
  const [sessionMemory, setSessionMemory] = useState<SessionMemory>(INITIAL_MEMORY);
  const [eventLogs, setEventLogs] = useState<EventLogEntry[]>([]);
  const [screenItems, setScreenItems] = useState<ScreenBroadcastItem[]>([]);

  const [cooldownRemainingSec, setCooldownRemainingSec] = useState(0);
  const [isBusy, setIsBusy] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [aiConfigured, setAiConfigured] = useState(true);

  const [ignoredCount, setIgnoredCount] = useState(0);
  const [acceptedCount, setAcceptedCount] = useState(0);
  const [proposalsCount, setProposalsCount] = useState(0);
  const [latencySamples, setLatencySamples] = useState<number[]>([]);

  // Real Microphone & Voice Output Refs
  const micAdapterRef = useRef<LiveMicrophoneAdapter | null>(null);
  if (!micAdapterRef.current) {
    micAdapterRef.current = new LiveMicrophoneAdapter();
  }
  const voicePlayerRef = useRef<NeoVoicePlayer | null>(null);
  if (!voicePlayerRef.current) {
    voicePlayerRef.current = new NeoVoicePlayer();
  }

  const micSupported = micAdapterRef.current.isSupported();
  const [micActive, setMicActive] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [audioLevel, setAudioLevel] = useState(0);
  const [captureMode, setCaptureMode] = useState<CaptureMode>('vad');
  const [manualRecording, setManualRecording] = useState(false);
  const [devices, setDevices] = useState<AudioDeviceOption[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');

  // Real TTS Voice States
  const [voiceName, setVoiceName] = useState<NeoVoiceName>('Kore');
  const [autoSpeakOnDirect, setAutoSpeakOnDirect] = useState(false);
  const [isGeneratingVoice, setIsGeneratingVoice] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [speakingScreenItemId, setSpeakingScreenItemId] = useState<string | null>(null);

  // Latest state refs for async audio callbacks
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const sessionRunningRef = useRef(sessionRunning);
  sessionRunningRef.current = sessionRunning;
  const activeProposalRef = useRef(activeProposal);
  activeProposalRef.current = activeProposal;
  const exchangesRef = useRef(exchanges);
  exchangesRef.current = exchanges;
  const sessionMemoryRef = useRef(sessionMemory);
  sessionMemoryRef.current = sessionMemory;
  const sessionConfigRef = useRef(sessionConfig);
  sessionConfigRef.current = sessionConfig;
  const cooldownRef = useRef(cooldownRemainingSec);
  cooldownRef.current = cooldownRemainingSec;
  const voiceNameRef = useRef(voiceName);
  voiceNameRef.current = voiceName;
  const autoSpeakRef = useRef(autoSpeakOnDirect);
  autoSpeakRef.current = autoSpeakOnDirect;

  useEffect(() => {
    checkNeoHealth()
      .then((res) => setAiConfigured(res.aiConfigured))
      .catch(() => setAiConfigured(false));
    listAudioInputDevices()
      .then((list) => {
        setDevices(list);
        if (list.length > 0 && !selectedDeviceId) {
          setSelectedDeviceId(list[0].deviceId);
        }
      })
      .catch(() => {});
  }, [selectedDeviceId]);

  // Session elapsed timer
  useEffect(() => {
    if (!sessionRunning || mode === 'OFF') return;
    const timer = window.setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [sessionRunning, mode]);

  // Cooldown countdown
  useEffect(() => {
    if (cooldownRemainingSec <= 0) return;
    const timer = window.setInterval(() => {
      setCooldownRemainingSec((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [cooldownRemainingSec]);

  const settleIdleState = useCallback((hasProposal: boolean) => {
    if (modeRef.current === 'OFF') {
      setNeoState('Assistant désactivé');
    } else if (hasProposal) {
      setNeoState('Proposition disponible');
    } else if (sessionRunningRef.current) {
      setNeoState('Écoute');
    } else {
      setNeoState('En veille');
    }
  }, []);

  const stopVoicePlayback = useCallback(() => {
    voicePlayerRef.current?.stop();
    setIsSpeaking(false);
    setSpeakingScreenItemId(null);
  }, []);

  const speakText = useCallback(
    async (text: string, screenItemId?: string) => {
      if (!text.trim()) return;
      stopVoicePlayback();
      setErrorMsg(null);
      setIsGeneratingVoice(true);
      try {
        const res = await synthesizeSpeechWithGemini({
          text,
          voiceName: voiceNameRef.current,
        });
        setIsGeneratingVoice(false);
        setIsSpeaking(true);
        if (screenItemId) {
          setSpeakingScreenItemId(screenItemId);
        }
        voicePlayerRef.current?.playWavBase64(
          res.audioBase64,
          () => {
            setIsSpeaking(false);
            setSpeakingScreenItemId(null);
          },
          (err) => {
            setIsSpeaking(false);
            setSpeakingScreenItemId(null);
            setErrorMsg(err);
          },
        );
      } catch (err) {
        setIsGeneratingVoice(false);
        setIsSpeaking(false);
        setSpeakingScreenItemId(null);
        const msg =
          err instanceof Error ? err.message : 'Erreur lors de la synthèse vocale NÉO.';
        setErrorMsg(msg);
      }
    },
    [stopVoicePlayback],
  );

  const handleModeChange = (nextMode: NeoMode) => {
    setMode(nextMode);
    setErrorMsg(null);
    if (nextMode === 'OFF') {
      setNeoState('Assistant désactivé');
      stopVoicePlayback();
      if (micActive) {
        micAdapterRef.current?.stop();
        setMicActive(false);
        setManualRecording(false);
      }
    } else if (activeProposal) {
      setNeoState('Proposition disponible');
    } else if (sessionRunning) {
      setNeoState('Écoute');
    } else {
      setNeoState('En veille');
    }
  };

  const handleToggleSession = () => {
    if (mode === 'OFF') {
      setMode('ACTIF');
    }
    setSessionRunning((prev) => {
      const next = !prev;
      if (next) {
        setNeoState(activeProposal ? 'Proposition disponible' : 'Écoute');
      } else {
        stopVoicePlayback();
        if (micActive) {
          micAdapterRef.current?.stop();
          setMicActive(false);
          setManualRecording(false);
        }
        setNeoState(activeProposal ? 'Proposition disponible' : 'En veille');
      }
      return next;
    });
  };

  // Direct Trainer Commands & Proposal Refinements (Priority 1, uses Gemini)
  const handleDirectCommand = useCallback(
    async (command: string, actionType: string, targetProposal?: NeoProposal) => {
      if (modeRef.current === 'OFF') return;
      if (!sessionRunningRef.current) setSessionRunning(true);

      setErrorMsg(null);
      setIsBusy(true);
      setNeoState('Analyse en cours');

      const timestamp = formatTimeNow();

      try {
        const result = await sendTrainerCommandWithGemini({
          command,
          actionType,
          sessionConfig: sessionConfigRef.current,
          recentExchanges: exchangesRef.current,
          currentProposal: targetProposal ?? activeProposalRef.current,
          sessionMemory: sessionMemoryRef.current,
        });

        const lastExchange = exchangesRef.current[exchangesRef.current.length - 1];
        const nextProposal: NeoProposal = {
          id: makeId('prop'),
          createdAt: timestamp,
          detectedIssue: result.detectedIssue,
          originQuote: targetProposal?.originQuote ?? lastExchange?.text ?? command,
          originSpeaker: targetProposal?.originSpeaker ?? 'Formateur',
          confidence: result.confidence,
          helpType: result.helpType,
          priority: 1,
          title: result.proposalTitle,
          content: result.proposalContent,
          screenSummary: result.screenSummary || result.proposalContent,
          status: 'pending',
          refinementCount: (targetProposal?.refinementCount ?? 0) + (targetProposal ? 1 : 0),
        };

        setActiveProposal(nextProposal);
        setLastSilenceReason(null);
        setProposalsCount((c) => c + 1);
        setLatencySamples((prev) => [...prev, result.latencyMs]);
        setSessionMemory((mem) => updateMemoryWithProposal(mem, nextProposal));
        setNeoState('Proposition disponible');

        const logEntry: EventLogEntry = {
          id: makeId('log'),
          time: timestamp,
          transcript: command,
          speaker: 'Formateur',
          eventType: 'Sollicitation formateur',
          analysis: result.detectedIssue,
          decision: 'Intervention prioritaire (Priorité 1 — sollicitation explicite)',
          proposedIntervention: `${nextProposal.helpType} : ${nextProposal.title}`,
          origin: 'saisie',
          latencyMs: result.latencyMs,
        };
        setEventLogs((prev) => [logEntry, ...prev]);

        if (autoSpeakRef.current && nextProposal.content) {
          speakText(nextProposal.content);
        }
      } catch (err) {
        const msg =
          err instanceof Error
            ? err.message
            : 'Erreur lors de la sollicitation directe de NÉO.';
        setErrorMsg(msg);
        settleIdleState(Boolean(activeProposalRef.current));
      } finally {
        setIsBusy(false);
      }
    },
    [settleIdleState, speakText],
  );

  // Process spoken (mic) or typed utterance via Gemini /api/neo/analyze
  const processLiveUtterance = useCallback(
    async (speaker: SpeakerRole, text: string, origin: InputOrigin) => {
      if (modeRef.current === 'OFF') return;
      if (!sessionRunningRef.current) {
        setSessionRunning(true);
      }

      // If voice input directly addresses "Néo" at the start, treat as Priority 1 direct command!
      const normalizedStart = text.trim().toLowerCase();
      if (
        origin === 'micro' &&
        (normalizedStart.startsWith('néo') || normalizedStart.startsWith('neo'))
      ) {
        await handleDirectCommand(text, 'commande_vocale');
        return;
      }

      setErrorMsg(null);
      setNeoState('Analyse en cours');
      setIsBusy(true);

      const timestamp = formatTimeNow();
      const currentExchanges = exchangesRef.current;
      const currentMemory = sessionMemoryRef.current;
      const currentCooldown = cooldownRef.current;
      const currentConfig = sessionConfigRef.current;
      const localInsights = detectLocalContextInsights(text, currentExchanges, currentMemory);

      try {
        const result = await analyzeUtteranceWithGemini({
          sessionConfig: currentConfig,
          mode: modeRef.current,
          utterance: { speaker, text, timestamp },
          recentExchanges: currentExchanges,
          sessionMemory: currentMemory,
          cooldownRemainingSec: currentCooldown,
        });

        const mergedInsights = Array.from(
          new Set([...localInsights, ...(result.contextInsights ?? [])]),
        );

        const isExplicitTrainer =
          speaker === 'Formateur' &&
          (text.toLowerCase().includes('néo') ||
            text.toLowerCase().includes('neo') ||
            result.priority === 1);

        const gate = evaluateInterventionGate({
          mode: modeRef.current,
          cooldownRemainingSec: currentCooldown,
          isExplicitTrainerCommand: isExplicitTrainer,
          priority: result.priority,
          shouldIntervene: result.shouldIntervene,
          category: result.category,
          contextInsights: mergedInsights,
          proposedContent: result.proposalContent ?? '',
          sessionMemory: currentMemory,
        });

        const exchangeEntry: TranscriptExchange = {
          id: makeId('ex'),
          timestamp,
          speaker,
          text,
          origin,
          category: result.category,
          contextInsights: mergedInsights,
          decisionSummary: gate.decisionSummary,
          priority: result.priority,
        };
        setExchanges((prev) => [...prev, exchangeEntry]);

        if (result.latencyMs > 0) {
          setLatencySamples((prev) => [...prev, result.latencyMs]);
        }

        let createdProposal: NeoProposal | null = null;
        if (gate.allowProposal && result.proposalContent) {
          createdProposal = {
            id: makeId('prop'),
            createdAt: timestamp,
            detectedIssue: result.detectedIssue,
            originQuote: text,
            originSpeaker: speaker,
            confidence: result.confidence,
            helpType: result.helpType,
            priority: result.priority,
            title: result.proposalTitle,
            content: result.proposalContent,
            screenSummary: result.screenSummary || result.proposalContent,
            status: 'pending',
            refinementCount: 0,
          };
          setActiveProposal(createdProposal);
          setLastSilenceReason(null);
          setProposalsCount((c) => c + 1);
          setCooldownRemainingSec(currentConfig.cooldownSeconds);
          setSessionMemory((mem) =>
            updateMemoryWithProposal(mem, createdProposal!, result.memoryUpdate),
          );
          setNeoState('Proposition disponible');

          if (autoSpeakRef.current && isExplicitTrainer) {
            speakText(createdProposal.content);
          }
        } else {
          setLastSilenceReason(gate.decisionSummary);
          settleIdleState(Boolean(activeProposalRef.current));
        }

        const logEntry: EventLogEntry = {
          id: makeId('log'),
          time: timestamp,
          transcript: text,
          speaker,
          eventType: result.category,
          analysis: result.detectedIssue,
          decision: gate.decisionSummary,
          proposedIntervention: createdProposal
            ? `${createdProposal.helpType} : ${createdProposal.title}`
            : '',
          origin,
          latencyMs: result.latencyMs,
        };
        setEventLogs((prev) => [logEntry, ...prev]);
      } catch (err) {
        const msg =
          err instanceof Error
            ? err.message
            : 'Erreur lors de l’analyse pédagogique via Gemini.';
        setErrorMsg(msg);
        settleIdleState(Boolean(activeProposalRef.current));
      } finally {
        setIsBusy(false);
      }
    },
    [handleDirectCommand, settleIdleState, speakText],
  );

  // Handle recorded audio segment -> Gemini Transcription -> Pedagogical Analysis
  const handleAudioSegment = useCallback(
    async (audioBase64: string, mimeType: string) => {
      if (modeRef.current === 'OFF') return;
      setIsTranscribing(true);
      setErrorMsg(null);
      setNeoState('Analyse en cours');

      try {
        const tr = await transcribeAudioWithGemini({
          audioBase64,
          mimeType,
          sessionTopic: sessionConfigRef.current.topic,
        });
        setIsTranscribing(false);

        const spokenText = tr.text.trim();
        if (!spokenText) {
          settleIdleState(Boolean(activeProposalRef.current));
          return;
        }

        await processLiveUtterance('Apprenant', spokenText, 'micro');
      } catch (err) {
        setIsTranscribing(false);
        const msg =
          err instanceof Error
            ? err.message
            : 'Erreur lors de la transcription audio du microphone.';
        setErrorMsg(msg);
        settleIdleState(Boolean(activeProposalRef.current));
      }
    },
    [processLiveUtterance, settleIdleState],
  );

  const startMicrophone = useCallback(
    async (deviceIdToUse?: string, modeToUse: CaptureMode = captureMode) => {
      const adapter = micAdapterRef.current;
      if (!adapter) return;
      if (!sessionRunningRef.current) setSessionRunning(true);
      setMicError(null);

      await adapter.start(
        {
          onAudioLevel: (lvl) => setAudioLevel(lvl),
          onSpeechDetected: (speaking) => {
            if (speaking) {
              setNeoState('Parole détectée');
            } else if (!activeProposalRef.current && modeRef.current !== 'OFF') {
              setNeoState('Écoute');
            }
          },
          onAudioSegment: (base64, mime) => {
            handleAudioSegment(base64, mime);
          },
          onStatusChange: (active, err) => {
            setMicActive(active);
            if (!active) setManualRecording(false);
            if (err) setMicError(err);
            if (active && !activeProposalRef.current) {
              setNeoState('Écoute');
            }
          },
        },
        deviceIdToUse,
        modeToUse,
      );

      // Refresh device labels after permission grant
      listAudioInputDevices().then(setDevices).catch(() => {});
    },
    [captureMode, handleAudioSegment],
  );

  const handleToggleMic = async () => {
    const adapter = micAdapterRef.current;
    if (!adapter) return;
    if (micActive) {
      adapter.stop();
      setMicActive(false);
      setManualRecording(false);
      setAudioLevel(0);
      settleIdleState(Boolean(activeProposal));
      return;
    }
    await startMicrophone(selectedDeviceId || undefined, captureMode);
  };

  const handleSelectDevice = async (deviceId: string) => {
    setSelectedDeviceId(deviceId);
    if (micActive) {
      await startMicrophone(deviceId, captureMode);
    }
  };

  const handleChangeCaptureMode = (nextCaptureMode: CaptureMode) => {
    setCaptureMode(nextCaptureMode);
    setManualRecording(false);
    micAdapterRef.current?.setCaptureMode(nextCaptureMode);
  };

  const handleToggleManualRecord = () => {
    const adapter = micAdapterRef.current;
    if (!adapter || !micActive) return;
    if (manualRecording) {
      adapter.stopManualRecordingAndSend();
      setManualRecording(false);
    } else {
      const started = adapter.startManualRecording();
      if (started) setManualRecording(true);
    }
  };

  useEffect(() => {
    return () => {
      micAdapterRef.current?.stop();
      voicePlayerRef.current?.stop();
    };
  }, []);

  // Proposal 6 actions
  const handleAcceptProposal = (prop: NeoProposal) => {
    setAcceptedCount((c) => c + 1);
    setActiveProposal(null);
    setNeoState('Intervention');
    setLastSilenceReason(`Proposition « ${prop.title} » intégrée par le formateur.`);
    window.setTimeout(() => settleIdleState(false), 2000);
  };

  const handleIgnoreProposal = (prop: NeoProposal) => {
    stopVoicePlayback();
    setIgnoredCount((c) => c + 1);
    setActiveProposal(null);
    setCooldownRemainingSec(sessionConfig.cooldownSeconds);
    setLastSilenceReason(`Proposition « ${prop.title} » ignorée — cooldown activé.`);
    settleIdleState(false);
  };

  const handleSendToScreen = (prop: NeoProposal) => {
    const item: ScreenBroadcastItem = {
      id: makeId('scr'),
      timestamp: formatTimeNow(),
      title: prop.title,
      helpType: prop.helpType,
      summary: prop.screenSummary,
      fullContent: prop.content,
    };
    setScreenItems((prev) => [item, ...prev]);
    setAcceptedCount((c) => c + 1);
    setActiveProposal(null);
    setNeoState('Intervention');
    setLastSilenceReason(`Synthèse « ${prop.title} » envoyée sur l'écran des apprenants.`);
    window.setTimeout(() => settleIdleState(false), 2000);
  };

  const handleResetSession = () => {
    stopVoicePlayback();
    setExchanges([]);
    setActiveProposal(null);
    setLastSilenceReason(null);
    setSessionMemory(INITIAL_MEMORY);
    setEventLogs([]);
    setScreenItems([]);
    setCooldownRemainingSec(0);
    setElapsedSeconds(0);
    setIgnoredCount(0);
    setAcceptedCount(0);
    setProposalsCount(0);
    setLatencySamples([]);
    setErrorMsg(null);
    settleIdleState(false);
  };

  const metrics: SessionMetrics = useMemo(() => {
    const questionsCount = exchanges.filter(
      (e) => e.category === 'Question' || e.category === "Demande d'exemple",
    ).length;
    const misunderstandingsCount = exchanges.filter(
      (e) =>
        e.category === 'Incompréhension' ||
        e.category === 'Confusion' ||
        e.category === 'Répétition',
    ).length;
    const avgResponseMs =
      latencySamples.length > 0
        ? Math.round(latencySamples.reduce((a, b) => a + b, 0) / latencySamples.length)
        : 0;

    return {
      questionsCount,
      misunderstandingsCount,
      proposalsCount,
      ignoredCount,
      acceptedCount,
      avgResponseMs,
    };
  }, [exchanges, latencySamples, proposalsCount, ignoredCount, acceptedCount]);

  const cooldownPercent =
    sessionConfig.cooldownSeconds > 0
      ? Math.round((cooldownRemainingSec / sessionConfig.cooldownSeconds) * 100)
      : 0;

  return (
    <div className="min-h-screen flex flex-col bg-[#0A0D12] text-slate-100">
      {/* Strict 3-Zone Top Bar */}
      <header className="border-b border-white/[0.08] bg-[#0A0D12]/95 backdrop-blur-sm sticky top-0 z-30">
        <div className="max-w-[1440px] mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-8">
          <button
            type="button"
            onClick={() => setActiveTab('cockpit')}
            className="text-lg font-bold tracking-tight text-white whitespace-nowrap shrink-0 font-[var(--font-display)] hover:text-cyan-300 transition-colors"
          >
            NÉO
          </button>

          <nav
            aria-label="Navigation principale"
            className="hidden md:flex items-center gap-6 text-sm font-medium"
          >
            {(
              [
                { id: 'cockpit', label: 'Cockpit' },
                { id: 'session', label: 'Session' },
                { id: 'journal', label: 'Journal' },
                {
                  id: 'ecran',
                  label:
                    screenItems.length > 0
                      ? `Écran apprenants (${screenItems.length})`
                      : 'Écran apprenants',
                },
                { id: 'architecture', label: 'Architecture' },
              ] as Array<{ id: WorkspaceTab; label: string }>
            ).map((nav) => {
              const active = activeTab === nav.id;
              return (
                <button
                  key={nav.id}
                  type="button"
                  onClick={() => setActiveTab(nav.id)}
                  className={`py-1 transition-colors whitespace-nowrap shrink-0 border-b-2 ${
                    active
                      ? 'text-cyan-400 border-cyan-400'
                      : 'text-slate-400 border-transparent hover:text-slate-100'
                  }`}
                >
                  {nav.label}
                </button>
              );
            })}
          </nav>

          <div className="flex items-center shrink-0">
            <button
              type="button"
              onClick={handleToggleSession}
              className={`px-4 py-2 text-xs font-semibold rounded-lg transition-colors whitespace-nowrap shrink-0 ${
                sessionRunning && mode !== 'OFF'
                  ? 'bg-white/[0.08] text-slate-100 hover:bg-white/[0.14] border border-white/[0.12]'
                  : 'bg-cyan-500 text-slate-950 hover:bg-cyan-400'
              }`}
            >
              {sessionRunning && mode !== 'OFF'
                ? 'Mettre en veille'
                : 'Démarrer la session'}
            </button>
          </div>
        </div>

        {/* Mobile navigation */}
        <div className="flex md:hidden items-center gap-4 px-4 pb-2.5 overflow-x-auto text-xs font-medium border-t border-white/[0.05]">
          {(
            [
              { id: 'cockpit', label: 'Cockpit' },
              { id: 'session', label: 'Session' },
              { id: 'journal', label: 'Journal' },
              { id: 'ecran', label: 'Écran' },
              { id: 'architecture', label: 'Architecture' },
            ] as Array<{ id: WorkspaceTab; label: string }>
          ).map((nav) => (
            <button
              key={nav.id}
              type="button"
              onClick={() => setActiveTab(nav.id)}
              className={`pt-2 whitespace-nowrap shrink-0 ${
                activeTab === nav.id ? 'text-cyan-400' : 'text-slate-400'
              }`}
            >
              {nav.label}
            </button>
          ))}
        </div>
      </header>

      <main className="flex-1 max-w-[1440px] w-full mx-auto px-4 sm:px-6 py-6 space-y-5">
        {!aiConfigured && (
          <div
            role="status"
            className="px-4 py-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs text-amber-200"
          >
            Clé IA serveur non détectée : configurez <span className="font-mono">GEMINI_API_KEY</span>{' '}
            dans le panneau <strong>Settings &gt; Secrets</strong> pour activer la transcription
            microphone, l&apos;analyse pédagogique et la voix de NÉO.
          </div>
        )}

        {activeTab === 'cockpit' && (
          <>
            {/* Cockpit Toolbar */}
            <section
              aria-label="État de NÉO, modes, voix et contexte de session"
              className="bg-[#11161F] border border-white/[0.08] rounded-xl p-4 space-y-4"
            >
              <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-4">
                <ListeningIndicator
                  state={neoState}
                  audioLevel={audioLevel}
                  micActive={micActive}
                />

                <div className="flex flex-wrap items-center gap-4">
                  {/* Voice Selector + Auto-Speak */}
                  <div className="flex items-center gap-2">
                    <Volume2 className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    <select
                      value={voiceName}
                      onChange={(e) => setVoiceName(e.target.value as NeoVoiceName)}
                      aria-label="Choisir la voix de NÉO"
                      className="px-2.5 py-1.5 text-xs text-slate-200 bg-[#0A0D12] border border-white/[0.08] rounded-lg focus:outline-none focus:border-cyan-400/70"
                    >
                      {VOICES.map((v) => (
                        <option key={v.id} value={v.id}>
                          Voix {v.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => setAutoSpeakOnDirect((v) => !v)}
                      className={`px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-colors whitespace-nowrap ${
                        autoSpeakOnDirect
                          ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/35'
                          : 'bg-[#0A0D12] text-slate-400 border-white/[0.08] hover:text-slate-200'
                      }`}
                      title="Lire automatiquement la réponse à voix haute lors d'une sollicitation directe"
                    >
                      Voix auto : {autoSpeakOnDirect ? 'Oui' : 'Non'}
                    </button>
                  </div>

                  {/* Mode Selector */}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-slate-400 whitespace-nowrap">Mode actif :</span>
                    <div
                      role="radiogroup"
                      aria-label="Mode de fonctionnement de NÉO"
                      className="flex flex-wrap items-center gap-1 p-1 bg-[#0A0D12] border border-white/[0.08] rounded-lg"
                    >
                      {MODES.map((m) => {
                        const active = mode === m.id;
                        return (
                          <button
                            key={m.id}
                            type="button"
                            role="radio"
                            aria-checked={active}
                            title={m.desc}
                            onClick={() => handleModeChange(m.id)}
                            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors whitespace-nowrap shrink-0 ${
                              active
                                ? m.id === 'OFF'
                                  ? 'bg-rose-500/20 text-rose-300 border border-rose-500/35'
                                  : 'bg-cyan-500 text-slate-950'
                                : 'text-slate-400 hover:text-slate-100 border border-transparent'
                            }`}
                          >
                            {m.id}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>

              {/* Session Info Strip + Visual Cooldown Bar */}
              <div className="pt-3 border-t border-white/[0.06] flex flex-col xl:flex-row xl:items-center justify-between gap-3 text-xs">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-slate-300">
                  <span className="font-semibold text-white">{sessionConfig.name}</span>
                  <span aria-hidden="true" className="text-slate-600">
                    ·
                  </span>
                  <span className="text-cyan-300">{sessionConfig.topic}</span>
                  <span aria-hidden="true" className="text-slate-600">
                    ·
                  </span>
                  <span className="text-slate-400">Niveau {sessionConfig.level}</span>
                  <span aria-hidden="true" className="text-slate-600">
                    ·
                  </span>
                  <span className="inline-flex items-center gap-1 text-slate-400 tabular-nums">
                    <Users className="w-3.5 h-3.5 text-slate-500" />
                    {sessionConfig.participantsCount} participants
                  </span>
                  <span aria-hidden="true" className="text-slate-600">
                    ·
                  </span>
                  <span className="inline-flex items-center gap-1 font-mono tabular-nums text-slate-300">
                    <Clock className="w-3.5 h-3.5 text-slate-500" />
                    {formatDurationMMSS(elapsedSeconds)} / {sessionConfig.durationMinutes} min
                  </span>
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-400 whitespace-nowrap">Cooldown :</span>
                    <div className="w-28 h-1.5 bg-[#0A0D12] rounded-full overflow-hidden border border-white/[0.06]">
                      <div
                        className={`h-full transition-all duration-300 ${
                          cooldownRemainingSec > 0 ? 'bg-amber-400' : 'bg-emerald-500/50'
                        }`}
                        style={{
                          width: cooldownRemainingSec > 0 ? `${cooldownPercent}%` : '0%',
                        }}
                      />
                    </div>
                    <span className="font-mono tabular-nums text-slate-300 w-10 text-right">
                      {cooldownRemainingSec > 0 ? `${cooldownRemainingSec} s` : 'Prêt'}
                    </span>
                  </div>
                  {cooldownRemainingSec > 0 && (
                    <button
                      type="button"
                      onClick={() => setCooldownRemainingSec(0)}
                      title="Réinitialiser le cooldown"
                      className="p-1 text-slate-400 hover:text-cyan-300 transition-colors"
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            </section>

            {/* Primary 2-Column Cockpit Workspace */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-stretch">
              <div className="lg:col-span-7 flex flex-col">
                <ExchangeStream
                  exchanges={exchanges}
                  mode={mode}
                  isBusy={isBusy}
                  isTranscribing={isTranscribing}
                  micActive={micActive}
                  micSupported={micSupported}
                  micError={micError}
                  audioLevel={audioLevel}
                  captureMode={captureMode}
                  manualRecording={manualRecording}
                  devices={devices}
                  selectedDeviceId={selectedDeviceId}
                  onSelectDevice={handleSelectDevice}
                  onChangeCaptureMode={handleChangeCaptureMode}
                  onToggleMic={handleToggleMic}
                  onToggleManualRecord={handleToggleManualRecord}
                  onSubmitUtterance={(speaker, text) =>
                    processLiveUtterance(speaker, text, 'saisie')
                  }
                />
              </div>

              <div className="lg:col-span-5 flex flex-col">
                <InterventionZone
                  neoState={neoState}
                  mode={mode}
                  proposal={activeProposal}
                  lastSilenceReason={lastSilenceReason}
                  isBusy={isBusy}
                  isSpeaking={isSpeaking && !speakingScreenItemId}
                  isGeneratingVoice={isGeneratingVoice}
                  errorMsg={errorMsg}
                  sessionMemory={sessionMemory}
                  cooldownRemainingSec={cooldownRemainingSec}
                  onAccept={handleAcceptProposal}
                  onIgnore={handleIgnoreProposal}
                  onReformulate={(prop) =>
                    handleDirectCommand(
                      'Néo, reformule cette proposition différemment et encore plus clairement.',
                      'reformulate',
                      prop,
                    )
                  }
                  onDevelop={(prop) =>
                    handleDirectCommand(
                      'Néo, développe cette proposition avec un exemple concret supplémentaire.',
                      'deepen',
                      prop,
                    )
                  }
                  onSendToScreen={handleSendToScreen}
                  onSpeakProposal={(prop) => speakText(`${prop.title}. ${prop.content}`)}
                  onStopVoice={stopVoicePlayback}
                  onDirectCommand={(cmd, action) => handleDirectCommand(cmd, action)}
                />
              </div>
            </div>
          </>
        )}

        {activeTab === 'session' && (
          <SessionConfigView
            config={sessionConfig}
            onChange={setSessionConfig}
            onResetSession={handleResetSession}
          />
        )}

        {activeTab === 'journal' && (
          <SupervisionJournalView logs={eventLogs} metrics={metrics} />
        )}

        {activeTab === 'ecran' && (
          <LearnerScreenView
            sessionConfig={sessionConfig}
            items={screenItems}
            speakingItemId={speakingScreenItemId}
            isGeneratingVoice={isGeneratingVoice}
            onSpeakItem={(item) => speakText(`${item.title}. ${item.fullContent}`, item.id)}
            onStopVoice={stopVoicePlayback}
            onRemoveItem={(id) =>
              setScreenItems((prev) => prev.filter((item) => item.id !== id))
            }
            onClearAll={() => setScreenItems([])}
            onBackToCockpit={() => setActiveTab('cockpit')}
          />
        )}

        {activeTab === 'architecture' && (
          <ArchitectureView
            aiConfigured={aiConfigured}
            micSupported={micSupported}
            micActive={micActive}
          />
        )}
      </main>
    </div>
  );
}
