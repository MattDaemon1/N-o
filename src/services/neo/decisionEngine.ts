import type {
  ContextInsight,
  ExchangeCategory,
  NeoMode,
  NeoProposal,
  PriorityLevel,
  SessionMemory,
  TranscriptExchange,
} from './types';

export interface AnalysisEvaluationInput {
  mode: NeoMode;
  cooldownRemainingSec: number;
  isExplicitTrainerCommand: boolean;
  priority: PriorityLevel;
  shouldIntervene: boolean;
  category: ExchangeCategory;
  contextInsights: ContextInsight[];
  proposedContent: string;
  sessionMemory: SessionMemory;
}

export interface GatekeeperDecision {
  allowProposal: boolean;
  decisionSummary: string;
  reasonCode:
    | 'OFF_MODE'
    | 'PASSIVE_SILENCE'
    | 'ON_DEMAND_SILENCE'
    | 'NO_VALUE_SILENCE'
    | 'COOLDOWN_ACTIVE'
    | 'DUPLICATE_PREVENTED'
    | 'APPROVED';
}

export function evaluateInterventionGate(input: AnalysisEvaluationInput): GatekeeperDecision {
  if (input.mode === 'OFF') {
    return {
      allowProposal: false,
      decisionSummary: 'Assistant désactivé — analyse ignorée',
      reasonCode: 'OFF_MODE',
    };
  }

  // Priority 1: explicit trainer command works in ACTIF, PASSIF, and SUR DEMANDE
  if (input.isExplicitTrainerCommand || input.priority === 1) {
    return {
      allowProposal: true,
      decisionSummary: 'Intervention prioritaire sur sollicitation explicite du formateur',
      reasonCode: 'APPROVED',
    };
  }

  if (input.mode === 'PASSIF') {
    return {
      allowProposal: false,
      decisionSummary: 'Mode PASSIF — échange analysé et consigné sans proposition spontanée',
      reasonCode: 'PASSIVE_SILENCE',
    };
  }

  if (input.mode === 'SUR DEMANDE') {
    return {
      allowProposal: false,
      decisionSummary: 'Mode SUR DEMANDE — NÉO reste silencieux en attente d’une sollicitation',
      reasonCode: 'ON_DEMAND_SILENCE',
    };
  }

  // Mode ACTIF checks
  if (!input.shouldIntervene || input.priority === 6 || !input.proposedContent.trim()) {
    return {
      allowProposal: false,
      decisionSummary: 'Silence intelligent — aucune intervention nécessaire',
      reasonCode: 'NO_VALUE_SILENCE',
    };
  }

  // Avoid repeating identical content already proposed in session
  const normalized = input.proposedContent.trim().toLowerCase().slice(0, 72);
  const alreadyGiven = input.sessionMemory.previousInterventions.some((prev) =>
    prev.trim().toLowerCase().includes(normalized),
  );
  if (alreadyGiven) {
    return {
      allowProposal: false,
      decisionSummary: 'Silence — réponse similaire déjà fournie dans la session',
      reasonCode: 'DUPLICATE_PREVENTED',
    };
  }

  // Respect cooldown unless critical priority 2 strong misunderstanding overrides?
  // Per spec: visual cooldown prevents repetitive proposals; Priority 1 always bypasses,
  // Priority 2-5 wait out active cooldown.
  if (input.cooldownRemainingSec > 0) {
    return {
      allowProposal: false,
      decisionSummary: `Cooldown actif (${input.cooldownRemainingSec} s) — proposition retenue pour éviter la surcharge`,
      reasonCode: 'COOLDOWN_ACTIVE',
    };
  }

  return {
    allowProposal: true,
    decisionSummary: `Proposition générée (Priorité ${input.priority})`,
    reasonCode: 'APPROVED',
  };
}

export function detectLocalContextInsights(
  utterance: string,
  recentExchanges: TranscriptExchange[],
  memory: SessionMemory,
): ContextInsight[] {
  const lower = utterance.toLowerCase();
  const insights: ContextInsight[] = [];

  const tokens = lower
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split(/\s+/)
    .filter((w) => w.length > 4);

  const askedMatch = memory.askedQuestions.some((q) => {
    const qLower = q.toLowerCase();
    return tokens.some((t) => qLower.includes(t));
  });

  const resolvedMatch = memory.resolvedTopics.some((topic) => {
    const tLower = topic.toLowerCase();
    return tokens.some((t) => tLower.includes(t));
  });

  const repeatedInRecent = recentExchanges.some((ex) => {
    const exLower = ex.text.toLowerCase();
    const shared = tokens.filter((t) => exLower.includes(t));
    return shared.length >= 2;
  });

  if (askedMatch || repeatedInRecent) {
    insights.push('Question déjà posée');
  }
  if (resolvedMatch) {
    insights.push('Question déjà résolue');
  }
  if (lower.includes('toujours pas') || lower.includes('revenir') || lower.includes('encore')) {
    insights.push('Difficulté persistante');
  }
  if (lower.includes('même chose') || lower.includes('pareil') || lower.includes('différence')) {
    insights.push('Confusion entre deux concepts');
  }

  return Array.from(new Set(insights));
}

export function updateMemoryWithProposal(
  memory: SessionMemory,
  proposal: NeoProposal,
  memoryUpdate?: {
    resolvedTopic?: string;
    persistentDifficulty?: string;
    confusedPair?: string;
    answeredQuestion?: string;
  },
): SessionMemory {
  const next: SessionMemory = {
    askedQuestions: [...memory.askedQuestions],
    resolvedTopics: [...memory.resolvedTopics],
    persistentDifficulties: [...memory.persistentDifficulties],
    confusedPairs: [...memory.confusedPairs],
    previousInterventions: [...memory.previousInterventions],
  };

  if (proposal.content && !next.previousInterventions.includes(proposal.content)) {
    next.previousInterventions.push(proposal.content);
  }

  if (memoryUpdate?.answeredQuestion && !next.askedQuestions.includes(memoryUpdate.answeredQuestion)) {
    next.askedQuestions.push(memoryUpdate.answeredQuestion);
  }
  if (memoryUpdate?.resolvedTopic && !next.resolvedTopics.includes(memoryUpdate.resolvedTopic)) {
    next.resolvedTopics.push(memoryUpdate.resolvedTopic);
  }
  if (
    memoryUpdate?.persistentDifficulty &&
    !next.persistentDifficulties.includes(memoryUpdate.persistentDifficulty)
  ) {
    next.persistentDifficulties.push(memoryUpdate.persistentDifficulty);
  }
  if (memoryUpdate?.confusedPair && !next.confusedPairs.includes(memoryUpdate.confusedPair)) {
    next.confusedPairs.push(memoryUpdate.confusedPair);
  }

  return next;
}
