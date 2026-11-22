import {
  BrainCircuit,
  Database,
  FileText,
  Mic,
  Monitor,
  Radio,
  UserSquare2,
  Volume2,
} from 'lucide-react';

interface ArchitectureViewProps {
  aiConfigured: boolean;
  micSupported: boolean;
  micActive: boolean;
}

export function ArchitectureView({
  aiConfigured,
  micSupported,
  micActive,
}: ArchitectureViewProps) {
  const modules = [
    {
      title: '1. Capture Microphone & VAD',
      interfaceName: 'LiveMicrophoneAdapter',
      status: micActive
        ? 'Actif (flux micro + détection vocale)'
        : micSupported
          ? 'Prêt (Web Audio API + MediaRecorder)'
          : 'Non disponible sur ce navigateur',
      active: micSupported,
      icon: Mic,
      description:
        'Capture l’audio réel du microphone avec détection automatique d’activité vocale (VAD) et sélection du périphérique.',
    },
    {
      title: '2. Transcription Audio (STT)',
      interfaceName: 'POST /api/neo/transcribe',
      status: aiConfigured
        ? 'Connecté (gemini-3.5-transcribe)'
        : 'Clé serveur requise (GEMINI_API_KEY)',
      active: aiConfigured,
      icon: Radio,
      description:
        'Transcrit fidèlement les segments audio captés en français avant leur évaluation pédagogique.',
    },
    {
      title: '3. Modèle LLM Pédagogique',
      interfaceName: 'POST /api/neo/analyze',
      status: aiConfigured
        ? 'Connecté (gemini-4-hydrogen)'
        : 'Clé serveur requise (GEMINI_API_KEY)',
      active: aiConfigured,
      icon: BrainCircuit,
      description:
        'Analyse contextuelle structurée par schéma JSON, respectant les 6 niveaux de priorité et les 4 modes.',
    },
    {
      title: '4. Synthèse Vocale (TTS)',
      interfaceName: 'POST /api/neo/speak',
      status: aiConfigured
        ? 'Connecté (gemini-3.8-flash-lite-tts)'
        : 'Clé serveur requise (GEMINI_API_KEY)',
      active: aiConfigured,
      icon: Volume2,
      description:
        'Génère une voix française posée et professionnelle (WAV 24 kHz) avec 5 timbres sélectionnables.',
    },
    {
      title: '5. Mémoire pédagogique de session',
      interfaceName: 'SessionMemory & DecisionEngine',
      status: 'Actif en mémoire de session',
      active: true,
      icon: Database,
      description:
        'Suit les questions déjà posées, les notions résolues, les difficultés persistantes et évite les doublons.',
    },
    {
      title: '6. Projection Écran Apprenants',
      interfaceName: 'ScreenBroadcastChannel',
      status: 'Actif (vue dédiée intégrée)',
      active: true,
      icon: Monitor,
      description:
        'Diffuse uniquement les synthèses explicitement validées par le formateur sans exposer le cockpit.',
    },
    {
      title: '7. Connexion Visioconférence',
      interfaceName: 'VideoConferenceConnector (Contrat)',
      status: 'Interface prête pour intégration externe',
      active: false,
      icon: UserSquare2,
      description:
        'Point d’extension prévu pour capter directement les pistes audio Zoom, Teams ou Google Meet.',
    },
    {
      title: '8. Import Supports de formation',
      interfaceName: 'CourseMaterialImporter (Contrat)',
      status: 'Interface prête pour intégration externe',
      active: false,
      icon: FileText,
      description:
        'Point d’extension prévu pour indexer le programme PDF, les diapositives et les exercices dans le contexte LLM.',
    },
  ];

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white tracking-tight">
          Architecture modulaire &amp; pipeline temps réel
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          État réel des briques audio, transcription, analyse IA et synthèse vocale actives dans NÉO.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {modules.map((mod) => {
          const Icon = mod.icon;
          return (
            <div
              key={mod.title}
              className="bg-[#11161F] border border-white/[0.08] rounded-xl p-5 space-y-2.5"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <Icon
                    className={`w-4 h-4 shrink-0 ${
                      mod.active ? 'text-cyan-400' : 'text-slate-500'
                    }`}
                  />
                  <h2 className="text-sm font-semibold text-white">{mod.title}</h2>
                </div>
                <span className="font-mono text-[11px] text-slate-400">{mod.interfaceName}</span>
              </div>

              <div
                className={`text-xs font-medium ${
                  mod.active ? 'text-emerald-400' : 'text-slate-400'
                }`}
              >
                {mod.status}
              </div>

              <p className="text-xs text-slate-400 leading-relaxed">{mod.description}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
