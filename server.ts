import 'dotenv/config';
import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import { GoogleGenAI, Type, ThinkingLevel } from '@google/genai';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = 3000;
const MODEL_ANALYSIS = 'gemini-4-hydrogen';
const MODEL_TRANSCRIBE = 'gemini-3.5-transcribe';
const MODEL_TTS = 'gemini-3.8-flash-lite-tts';

function getGeminiClient(apiVersion: 'v1beta' | 'v1' = 'v1beta'): GoogleGenAI {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    throw new Error('GEMINI_API_KEY manquante dans les secrets (Settings > Secrets).');
  }
  return new GoogleGenAI({
    apiKey,
    apiVersion,
    httpOptions: {
      headers: {
        'User-Agent': 'aistudio-build',
      },
    },
  });
}

async function withRetry<T>(fn: () => Promise<T>, maxRetries = 2): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      const msg = err instanceof Error ? err.message : String(err);
      const isTransient =
        msg.includes('503') ||
        msg.includes('UNAVAILABLE') ||
        msg.includes('high demand') ||
        msg.includes('429') ||
        msg.includes('ECONNRESET');
      if (!isTransient || attempt === maxRetries) {
        throw err;
      }
      await new Promise((r) => setTimeout(r, 700 * (attempt + 1)));
    }
  }
  throw lastErr;
}

const ANALYSIS_SCHEMA = {
  type: Type.OBJECT,
  properties: {
    category: {
      type: Type.STRING,
      description:
        "Catégorie exacte : 'Question', 'Incompréhension', 'Confusion', 'Répétition', 'Demande d\\'exemple', 'Hors sujet', ou 'Échange normal'.",
    },
    contextInsights: {
      type: Type.ARRAY,
      items: { type: Type.STRING },
      description:
        "Signaux contextuels parmi : 'Question déjà posée', 'Question déjà résolue', 'Difficulté persistante', 'Explication insuffisante', 'Confusion entre deux concepts', 'Intervention formateur requise'.",
    },
    detectedIssue: {
      type: Type.STRING,
      description: 'Problème pédagogique détecté en 1 phrase courte, ou "Aucune difficulté détectée".',
    },
    shouldIntervene: {
      type: Type.BOOLEAN,
      description:
        "Vrai uniquement si une intervention apporte une réelle valeur pédagogique. Privilégier le silence (false) sur les échanges normaux, hors-sujets ou déjà résolus.",
    },
    priority: {
      type: Type.INTEGER,
      description:
        "Niveau de priorité de 1 à 6 : 1=Intervention explicite du formateur, 2=Incompréhension forte détectée, 3=Question pertinente non résolue, 4=Demande d'exemple, 5=Reformulation utile, 6=Silence (aucune valeur).",
    },
    decisionReason: {
      type: Type.STRING,
      description: 'Justification concise de la décision prise (1 phrase).',
    },
    helpType: {
      type: Type.STRING,
      description:
        "Type d'aide recommandé : 'Reformulation', 'Exemple concret', 'Analogie', 'Explication complémentaire', 'Détection d\\'incompréhension', ou 'Synthèse'.",
    },
    confidence: {
      type: Type.INTEGER,
      description: 'Score de confiance de 0 à 100.',
    },
    proposalTitle: {
      type: Type.STRING,
      description: 'Titre court et exploitable (4 à 8 mots).',
    },
    proposalContent: {
      type: Type.STRING,
      description:
        'Proposition courte, calme et directement exploitable par le formateur (2 à 4 phrases max, adaptée au niveau des apprenants). Vide si shouldIntervene est false.',
    },
    screenSummary: {
      type: Type.STRING,
      description:
        'Synthèse courte (1 à 2 phrases) prête à être affichée sur l’écran des apprenants si le formateur le souhaite.',
    },
    memoryUpdate: {
      type: Type.OBJECT,
      properties: {
        resolvedTopic: { type: Type.STRING },
        persistentDifficulty: { type: Type.STRING },
        confusedPair: { type: Type.STRING },
        answeredQuestion: { type: Type.STRING },
      },
    },
  },
  required: [
    'category',
    'contextInsights',
    'detectedIssue',
    'shouldIntervene',
    'priority',
    'decisionReason',
    'helpType',
    'confidence',
    'proposalTitle',
    'proposalContent',
    'screenSummary',
  ],
};

const COMMAND_SCHEMA = {
  type: Type.OBJECT,
  properties: {
    helpType: {
      type: Type.STRING,
      description:
        "Type d'aide : 'Reformulation', 'Exemple concret', 'Analogie', 'Explication complémentaire', 'Détection d\\'incompréhension', ou 'Synthèse'.",
    },
    detectedIssue: {
      type: Type.STRING,
      description: 'Intention ou besoin identifié suite à la sollicitation du formateur.',
    },
    confidence: {
      type: Type.INTEGER,
      description: 'Niveau de confiance de 0 à 100.',
    },
    proposalTitle: {
      type: Type.STRING,
      description: 'Titre concis (4 à 8 mots).',
    },
    proposalContent: {
      type: Type.STRING,
      description:
        'Réponse claire, concise et directement exploitable pendant la formation (2 à 4 phrases max, sans bavardage).',
    },
    screenSummary: {
      type: Type.STRING,
      description: 'Version synthétique en 1 ou 2 phrases affichable aux apprenants.',
    },
  },
  required: [
    'helpType',
    'detectedIssue',
    'confidence',
    'proposalTitle',
    'proposalContent',
    'screenSummary',
  ],
};

const NEO_SYSTEM_INSTRUCTION = `Tu es NÉO, un assistant pédagogique intelligent conçu pour accompagner un formateur pendant ses sessions de formation, en présentiel comme à distance.
Tu n'es pas un chatbot classique : tu es un collègue pédagogique discret, calme, pragmatique et pertinent.
Règles strictes :
- Réponds toujours en français.
- Tes propositions doivent être courtes (2 à 4 phrases maximum), directement exploitables par le formateur.
- Privilégie les exemples concrets, les analogies simples et les reformulations claires adaptées au niveau indiqué.
- Ne monopolise jamais la parole, ne contredis jamais le formateur inutilement.
- Ne répète jamais une réponse déjà présente dans les interventions précédentes de la mémoire de session.
- Privilégie le SILENCE (shouldIntervene: false, priority: 6) lorsque la phrase est un échange normal, un hors-sujet bénin, une question déjà résolue, ou si l'intervention n'apporte aucune valeur.`;

function formatApiError(err: unknown, fallback: string): string {
  const raw = err instanceof Error ? err.message : fallback;
  try {
    const parsed = JSON.parse(raw);
    if (parsed?.error?.message) {
      return parsed.error.message;
    }
  } catch {
    // not JSON
  }
  return raw;
}

async function createApp() {
  const app = express();
  app.use(express.json({ limit: '15mb' }));

  app.get('/api/health', (_req, res) => {
    res.json({
      ok: true,
      aiConfigured: Boolean(process.env.GEMINI_API_KEY),
      models: {
        analysis: MODEL_ANALYSIS,
        transcription: MODEL_TRANSCRIBE,
        tts: MODEL_TTS,
      },
    });
  });

  app.post('/api/neo/transcribe', async (req, res) => {
    const startMs = Date.now();
    try {
      const { audioBase64, mimeType, sessionTopic } = req.body ?? {};
      if (!audioBase64 || typeof audioBase64 !== 'string') {
        res.status(400).json({ error: 'Flux audio manquant.' });
        return;
      }

      const cleanMime =
        typeof mimeType === 'string' && mimeType.includes('/')
          ? mimeType.split(';')[0].trim()
          : 'audio/webm';

      const aiBeta = getGeminiClient('v1beta');
      const promptText = `Transcris fidèlement la parole en français dans cet extrait audio issu d'une session de formation${
        sessionTopic ? ` portant sur « ${sessionTopic} »` : ''
      }. Retourne uniquement le texte prononcé, sans préambule ni commentaire. Si l'extrait ne contient aucune parole intelligible (silence ou bruit ambiant), retourne une chaîne vide.`;

      const contents = {
        parts: [
          {
            inlineData: {
              mimeType: cleanMime,
              data: audioBase64,
            },
          },
          { text: promptText },
        ],
      };

      let response;
      try {
        response = await withRetry(() =>
          aiBeta.models.generateContent({
            model: MODEL_TRANSCRIBE,
            contents,
          }),
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : '';
        if (msg.includes('404') || msg.includes('NOT_FOUND') || msg.includes('not found')) {
          // Multimodal fallback using active gemini-4-hydrogen model when dedicated transcribe model is unavailable
          response = await withRetry(() =>
            aiBeta.models.generateContent({
              model: MODEL_ANALYSIS,
              contents,
              config: { thinkingConfig: { thinkingLevel: ThinkingLevel.LOW } },
            }),
          );
        } else {
          throw err;
        }
      }

      const text = (response.text ?? '').trim();
      res.json({
        text,
        latencyMs: Date.now() - startMs,
      });
    } catch (err) {
      const message = formatApiError(err, 'Erreur lors de la transcription audio.');
      if (message.toLowerCase().includes('audio data is empty')) {
        res.json({ text: '', latencyMs: Date.now() - startMs });
        return;
      }
      console.error('[NÉO /api/neo/transcribe]', message);
      res.status(500).json({
        error: message,
        latencyMs: Date.now() - startMs,
      });
    }
  });

  app.post('/api/neo/analyze', async (req, res) => {
    const startMs = Date.now();
    try {
      const { sessionConfig, mode, utterance, recentExchanges, sessionMemory, cooldownRemainingSec } =
        req.body ?? {};

      if (!utterance?.text || typeof utterance.text !== 'string') {
        res.status(400).json({ error: 'Texte de transcription manquant.' });
        return;
      }

      const ai = getGeminiClient('v1beta');

      const prompt = JSON.stringify(
        {
          session: sessionConfig,
          modeActif: mode,
          cooldownRestantSecondes: cooldownRemainingSec ?? 0,
          memoireSession: sessionMemory,
          derniersEchanges: (recentExchanges ?? []).slice(-8),
          nouvelEchangeAAnalyser: utterance,
        },
        null,
        2,
      );

      const response = await withRetry(() =>
        ai.models.generateContent({
          model: MODEL_ANALYSIS,
          contents: `Analyse ce nouvel échange de formation en tenant compte du fil conversationnel et de la mémoire pédagogique.\n\n${prompt}`,
          config: {
            systemInstruction: NEO_SYSTEM_INSTRUCTION,
            responseMimeType: 'application/json',
            responseSchema: ANALYSIS_SCHEMA,
            thinkingConfig: { thinkingLevel: ThinkingLevel.LOW },
          },
        }),
      );

      const rawText = (response.text ?? '{}').trim();
      const parsed = JSON.parse(rawText);

      res.json({
        ...parsed,
        latencyMs: Date.now() - startMs,
      });
    } catch (err) {
      const message = formatApiError(err, 'Erreur lors de l’analyse Gemini.');
      console.error('[NÉO /api/neo/analyze]', message);
      res.status(500).json({
        error: message,
        latencyMs: Date.now() - startMs,
      });
    }
  });

  app.post('/api/neo/command', async (req, res) => {
    const startMs = Date.now();
    try {
      const { command, actionType, sessionConfig, recentExchanges, currentProposal, sessionMemory } =
        req.body ?? {};

      if (!command || typeof command !== 'string') {
        res.status(400).json({ error: 'Commande formateur manquante.' });
        return;
      }

      const ai = getGeminiClient('v1beta');

      const prompt = JSON.stringify(
        {
          demandeFormateur: command,
          typeAction: actionType ?? 'libre',
          session: sessionConfig,
          propositionActuelle: currentProposal ?? null,
          memoireSession: sessionMemory,
          derniersEchanges: (recentExchanges ?? []).slice(-8),
        },
        null,
        2,
      );

      const response = await withRetry(() =>
        ai.models.generateContent({
          model: MODEL_ANALYSIS,
          contents: `Le formateur te sollicite directement (Priorité 1). Réponds de manière concise, pragmatique et immédiatement exploitable.\n\n${prompt}`,
          config: {
            systemInstruction: NEO_SYSTEM_INSTRUCTION,
            responseMimeType: 'application/json',
            responseSchema: COMMAND_SCHEMA,
            thinkingConfig: { thinkingLevel: ThinkingLevel.LOW },
          },
        }),
      );

      const rawText = (response.text ?? '{}').trim();
      const parsed = JSON.parse(rawText);

      res.json({
        ...parsed,
        latencyMs: Date.now() - startMs,
      });
    } catch (err) {
      const message = formatApiError(err, 'Erreur lors de la commande Gemini.');
      console.error('[NÉO /api/neo/command]', message);
      res.status(500).json({
        error: message,
        latencyMs: Date.now() - startMs,
      });
    }
  });

  app.post('/api/neo/speak', async (req, res) => {
    const startMs = Date.now();
    try {
      const { text, voiceName } = req.body ?? {};
      if (!text || typeof text !== 'string') {
        res.status(400).json({ error: 'Texte à vocaliser manquant.' });
        return;
      }

      const allowedVoices = new Set(['Kore', 'Charon', 'Fenrir', 'Puck', 'Zephyr']);
      const selectedVoice = allowedVoices.has(voiceName) ? voiceName : 'Kore';

      const ai = getGeminiClient('v1beta');
      const response = await withRetry(() =>
        ai.models.generateContent({
          model: MODEL_TTS,
          contents: [
            {
              role: 'user',
              parts: [
                {
                  text,
                  speechMetadata: {
                    style:
                      'Voix posée, claire, calme et professionnelle de formateur francophone.',
                  },
                },
              ],
            },
          ],
          config: {
            responseModalities: ['AUDIO'],
            speechConfig: {
              voiceConfig: {
                prebuiltVoiceConfig: { voiceName: selectedVoice },
              },
            },
          },
        }),
      );

      const base64Audio = response.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data;
      if (!base64Audio) {
        res.status(502).json({ error: 'Aucun flux audio généré par le modèle TTS.' });
        return;
      }

      res.json({
        audioBase64: base64Audio,
        mimeType: 'audio/wav',
        latencyMs: Date.now() - startMs,
      });
    } catch (err) {
      const message = formatApiError(err, 'Erreur lors de la synthèse vocale.');
      console.error('[NÉO /api/neo/speak]', message);
      res.status(500).json({
        error: message,
        latencyMs: Date.now() - startMs,
      });
    }
  });

  if (process.env.NODE_ENV !== 'production') {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.resolve(__dirname, 'dist');
    app.use(express.static(distPath));
    app.get('*all', (_req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`NÉO Cockpit serveur prêt sur http://0.0.0.0:${PORT}`);
  });
}

createApp().catch((err) => {
  console.error('Échec du démarrage du serveur NÉO :', err);
  process.exit(1);
});
