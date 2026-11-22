export type NeoState =
  | 'En veille'
  | 'Écoute'
  | 'Parole détectée'
  | 'Analyse en cours'
  | 'Proposition disponible'
  | 'Intervention'
  | 'Assistant désactivé';

export type NeoMode = 'ACTIF' | 'PASSIF' | 'SUR DEMANDE' | 'OFF';

export type ExchangeCategory =
  | 'Question'
  | 'Incompréhension'
  | 'Confusion'
  | 'Répétition'
  | "Demande d'exemple"
  | 'Hors sujet'
  | 'Échange normal';

export type HelpType =
  | 'Reformulation'
  | 'Exemple concret'
  | 'Analogie'
  | 'Explication complémentaire'
  | "Détection d'incompréhension"
  | 'Synthèse';

export type PriorityLevel = 1 | 2 | 3 | 4 | 5 | 6;

export type ContextInsight =
  | 'Question déjà posée'
  | 'Question déjà résolue'
  | 'Difficulté persistante'
  | 'Explication insuffisante'
  | 'Confusion entre deux concepts'
  | 'Intervention formateur requise';

export type LearnerLevel = 'Débutant' | 'Intermédiaire' | 'Avancé' | 'Mixte';

export type InputOrigin = 'micro' | 'saisie';

export type SpeakerRole = 'Apprenant' | 'Formateur';

export type NeoVoiceName = 'Kore' | 'Charon' | 'Fenrir' | 'Puck' | 'Zephyr';

export interface SessionConfig {
  name: string;
  topic: string;
  level: LearnerLevel;
  objectives: string;
  participantsCount: number;
  durationMinutes: number;
  cooldownSeconds: number;
}

export interface TranscriptExchange {
  id: string;
  timestamp: string;
  speaker: SpeakerRole;
  text: string;
  origin: InputOrigin;
  category: ExchangeCategory;
  contextInsights: ContextInsight[];
  decisionSummary: string;
  priority: PriorityLevel;
}

export type ProposalStatus = 'pending' | 'accepted' | 'ignored' | 'sent_to_screen';

export interface NeoProposal {
  id: string;
  createdAt: string;
  detectedIssue: string;
  originQuote: string;
  originSpeaker: SpeakerRole;
  confidence: number;
  helpType: HelpType;
  priority: PriorityLevel;
  title: string;
  content: string;
  screenSummary: string;
  status: ProposalStatus;
  refinementCount: number;
}

export interface SessionMemory {
  askedQuestions: string[];
  resolvedTopics: string[];
  persistentDifficulties: string[];
  confusedPairs: string[];
  previousInterventions: string[];
}

export interface EventLogEntry {
  id: string;
  time: string;
  transcript: string;
  speaker: SpeakerRole;
  eventType: ExchangeCategory | 'Sollicitation formateur';
  analysis: string;
  decision: string;
  proposedIntervention: string;
  origin: InputOrigin;
  latencyMs: number;
}

export interface SessionMetrics {
  questionsCount: number;
  misunderstandingsCount: number;
  proposalsCount: number;
  ignoredCount: number;
  acceptedCount: number;
  avgResponseMs: number;
}

export interface ScreenBroadcastItem {
  id: string;
  timestamp: string;
  title: string;
  helpType: HelpType;
  summary: string;
  fullContent: string;
}
