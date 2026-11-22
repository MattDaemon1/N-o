import type {
  ContextInsight,
  ExchangeCategory,
  HelpType,
  NeoMode,
  NeoProposal,
  NeoVoiceName,
  PriorityLevel,
  SessionConfig,
  SessionMemory,
  SpeakerRole,
  TranscriptExchange,
} from './types';

export interface TranscribeResponse {
  text: string;
  latencyMs: number;
}

export interface AnalyzeResponse {
  category: ExchangeCategory;
  contextInsights: ContextInsight[];
  detectedIssue: string;
  shouldIntervene: boolean;
  priority: PriorityLevel;
  decisionReason: string;
  helpType: HelpType;
  confidence: number;
  proposalTitle: string;
  proposalContent: string;
  screenSummary: string;
  memoryUpdate?: {
    resolvedTopic?: string;
    persistentDifficulty?: string;
    confusedPair?: string;
    answeredQuestion?: string;
  };
  latencyMs: number;
}

export interface CommandResponse {
  helpType: HelpType;
  detectedIssue: string;
  confidence: number;
  proposalTitle: string;
  proposalContent: string;
  screenSummary: string;
  latencyMs: number;
}

export interface SpeakResponse {
  audioBase64: string;
  mimeType: string;
  latencyMs: number;
}

export async function checkNeoHealth(): Promise<{
  ok: boolean;
  aiConfigured: boolean;
  models?: {
    analysis: string;
    transcription: string;
    tts: string;
  };
}> {
  const res = await fetch('/api/health');
  if (!res.ok) {
    throw new Error('Impossible de joindre le serveur NÉO.');
  }
  return res.json();
}

export async function transcribeAudioWithGemini(params: {
  audioBase64: string;
  mimeType: string;
  sessionTopic?: string;
}): Promise<TranscribeResponse> {
  const res = await fetch('/api/neo/transcribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error || 'Erreur lors de la transcription audio.');
  }
  return data as TranscribeResponse;
}

export async function analyzeUtteranceWithGemini(params: {
  sessionConfig: SessionConfig;
  mode: NeoMode;
  utterance: { speaker: SpeakerRole; text: string; timestamp: string };
  recentExchanges: TranscriptExchange[];
  sessionMemory: SessionMemory;
  cooldownRemainingSec: number;
}): Promise<AnalyzeResponse> {
  const res = await fetch('/api/neo/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error || 'Erreur lors de l’analyse pédagogique IA.');
  }
  return data as AnalyzeResponse;
}

export async function sendTrainerCommandWithGemini(params: {
  command: string;
  actionType: string;
  sessionConfig: SessionConfig;
  recentExchanges: TranscriptExchange[];
  currentProposal: NeoProposal | null;
  sessionMemory: SessionMemory;
}): Promise<CommandResponse> {
  const res = await fetch('/api/neo/command', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error || 'Erreur lors de l’exécution de la commande.');
  }
  return data as CommandResponse;
}

export async function synthesizeSpeechWithGemini(params: {
  text: string;
  voiceName: NeoVoiceName;
}): Promise<SpeakResponse> {
  const res = await fetch('/api/neo/speak', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error || 'Erreur lors de la synthèse vocale NÉO.');
  }
  return data as SpeakResponse;
}
