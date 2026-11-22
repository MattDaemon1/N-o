import { MonitorUp, Trash2, Volume2, VolumeX } from 'lucide-react';
import type { ScreenBroadcastItem, SessionConfig } from '../services/neo/types';

interface LearnerScreenViewProps {
  sessionConfig: SessionConfig;
  items: ScreenBroadcastItem[];
  speakingItemId: string | null;
  isGeneratingVoice: boolean;
  onSpeakItem: (item: ScreenBroadcastItem) => void;
  onStopVoice: () => void;
  onRemoveItem: (id: string) => void;
  onClearAll: () => void;
  onBackToCockpit: () => void;
}

export function LearnerScreenView({
  sessionConfig,
  items,
  speakingItemId,
  isGeneratingVoice,
  onSpeakItem,
  onStopVoice,
  onRemoveItem,
  onClearAll,
  onBackToCockpit,
}: LearnerScreenViewProps) {
  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="text-xs font-medium text-cyan-400">
            Affichage partagé · {sessionConfig.name}
          </div>
          <h1 className="text-2xl font-semibold text-white tracking-tight mt-1">
            {sessionConfig.topic}
          </h1>
        </div>

        <div className="flex items-center gap-2">
          {items.length > 0 && (
            <button
              type="button"
              onClick={() => {
                onStopVoice();
                onClearAll();
              }}
              className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-300 hover:text-white bg-[#11161F] border border-white/[0.08] rounded-lg transition-colors whitespace-nowrap"
            >
              <Trash2 className="w-3.5 h-3.5 shrink-0" />
              <span>Effacer l&apos;écran</span>
            </button>
          )}
          <button
            type="button"
            onClick={onBackToCockpit}
            className="px-3.5 py-2 text-xs font-medium text-slate-950 bg-cyan-500 hover:bg-cyan-400 rounded-lg transition-colors whitespace-nowrap"
          >
            Retour au cockpit
          </button>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="bg-[#11161F] border border-white/[0.08] rounded-xl py-16 px-6 text-center space-y-3">
          <MonitorUp className="w-8 h-8 text-slate-500 mx-auto" />
          <h2 className="text-lg font-medium text-slate-200">
            Aucune synthèse projetée pour les apprenants
          </h2>
          <p className="text-sm text-slate-400 max-w-lg mx-auto">
            Lorsque le formateur clique sur « Envoyer à l&apos;écran » sur une proposition de NÉO,
            le point clé s&apos;affiche ici dans un format épuré, lisible en présentiel comme en visioconférence.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((item, idx) => {
            const isCurrentlySpeaking = speakingItemId === item.id;
            return (
              <article
                key={item.id}
                className={`bg-[#11161F] border rounded-xl p-6 space-y-3 ${
                  idx === 0 ? 'border-cyan-500/40' : 'border-white/[0.08] opacity-80'
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400 tabular-nums">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-cyan-400">{item.helpType}</span>
                    <span aria-hidden="true">·</span>
                    <span className="font-mono">{item.timestamp}</span>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={isGeneratingVoice}
                      onClick={() =>
                        isCurrentlySpeaking ? onStopVoice() : onSpeakItem(item)
                      }
                      className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-slate-300 hover:text-cyan-300 bg-white/[0.04] border border-white/[0.08] rounded-md transition-colors"
                    >
                      {isCurrentlySpeaking ? (
                        <>
                          <VolumeX className="w-3.5 h-3.5" />
                          <span>Arrêter lecture</span>
                        </>
                      ) : (
                        <>
                          <Volume2 className="w-3.5 h-3.5" />
                          <span>
                            {isGeneratingVoice ? 'Synthèse…' : 'Voix de NÉO'}
                          </span>
                        </>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => onRemoveItem(item.id)}
                      className="px-2.5 py-1 text-xs text-slate-400 hover:text-rose-300 bg-white/[0.03] border border-white/[0.08] rounded-md transition-colors"
                    >
                      Retirer
                    </button>
                  </div>
                </div>

                <h2 className="text-xl font-semibold text-white tracking-tight">{item.title}</h2>
                <p className="text-base text-slate-200 leading-relaxed">{item.fullContent}</p>
                {item.summary && (
                  <div className="pt-3 border-t border-white/[0.06] text-sm font-medium text-cyan-300">
                    À retenir : {item.summary}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
