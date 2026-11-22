import {
  Activity,
  BrainCircuit,
  CheckCircle2,
  EyeOff,
  Mic,
  PauseCircle,
  Sparkles,
} from 'lucide-react';
import type { NeoState } from '../services/neo/types';

interface ListeningIndicatorProps {
  state: NeoState;
  audioLevel?: number;
  micActive?: boolean;
}

const STATE_META: Record<
  NeoState,
  {
    colorClass: string;
    icon: typeof Mic;
    description: string;
  }
> = {
  'En veille': {
    colorClass: 'text-slate-400',
    icon: PauseCircle,
    description: 'Session en pause ou prête à démarrer',
  },
  Écoute: {
    colorClass: 'text-cyan-400',
    icon: Mic,
    description: 'Observation discrète des échanges',
  },
  'Parole détectée': {
    colorClass: 'text-emerald-400',
    icon: Activity,
    description: 'Capture d’une prise de parole',
  },
  'Analyse en cours': {
    colorClass: 'text-amber-400',
    icon: BrainCircuit,
    description: 'Évaluation pédagogique contextuelle',
  },
  'Proposition disponible': {
    colorClass: 'text-cyan-300',
    icon: Sparkles,
    description: 'Suggestion prête pour le formateur',
  },
  Intervention: {
    colorClass: 'text-emerald-300',
    icon: CheckCircle2,
    description: 'Aide activée par le formateur',
  },
  'Assistant désactivé': {
    colorClass: 'text-rose-400',
    icon: EyeOff,
    description: 'Analyse et suggestions coupées',
  },
};

const WAVE_BARS = [0.42, 0.78, 1.0, 0.65, 0.9, 0.52, 0.7];

export function ListeningIndicator({
  state,
  audioLevel = 0,
  micActive = false,
}: ListeningIndicatorProps) {
  const meta = STATE_META[state];
  const Icon = meta.icon;
  const isListeningWave = state === 'Écoute' || state === 'Parole détectée';

  return (
    <div className="flex items-center gap-3 min-w-0">
      <div className={`flex items-center gap-2 shrink-0 ${meta.colorClass}`}>
        <Icon className="w-4 h-4 shrink-0" aria-hidden="true" />
        <span className="text-sm font-semibold tracking-tight whitespace-nowrap">{state}</span>
      </div>

      {isListeningWave && (
        <div
          className="flex items-center gap-1 h-4 px-1"
          aria-label={
            micActive
              ? 'Indicateur acoustique microphone actif'
              : 'Indicateur visuel d’écoute active'
          }
        >
          {WAVE_BARS.map((base, idx) => {
            const dynamicScale = micActive
              ? Math.max(0.24, Math.min(1, base * (0.35 + audioLevel * 1.4)))
              : undefined;
            return (
              <span
                key={idx}
                className={`w-[2.5px] h-3.5 rounded-full ${
                  state === 'Parole détectée' ? 'bg-emerald-400' : 'bg-cyan-400'
                } ${micActive ? 'transition-transform duration-75' : 'animate-neo-wave'}`}
                style={
                  micActive
                    ? { transform: `scaleY(${dynamicScale})` }
                    : { animationDelay: `${idx * 110}ms` }
                }
              />
            );
          })}
        </div>
      )}

      <span className="hidden xl:inline text-xs text-slate-400 truncate">
        {meta.description}
      </span>
    </div>
  );
}
