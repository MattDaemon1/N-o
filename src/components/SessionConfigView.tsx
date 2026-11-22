import { RotateCcw } from 'lucide-react';
import { SESSION_TEMPLATES } from '../services/neo/templates';
import type { LearnerLevel, SessionConfig } from '../services/neo/types';

interface SessionConfigViewProps {
  config: SessionConfig;
  onChange: (next: SessionConfig) => void;
  onResetSession: () => void;
}

const LEVELS: LearnerLevel[] = ['Débutant', 'Intermédiaire', 'Avancé', 'Mixte'];

export function SessionConfigView({
  config,
  onChange,
  onResetSession,
}: SessionConfigViewProps) {
  const updateField = <K extends keyof SessionConfig>(key: K, value: SessionConfig[K]) => {
    onChange({ ...config, [key]: value });
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-white tracking-tight">
            Configuration de la session de formation
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Ces paramètres guident NÉO pour ajuster le vocabulaire, la pertinence et la discrétion de ses aides.
          </p>
        </div>

        <button
          type="button"
          onClick={onResetSession}
          className="flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-slate-300 hover:text-white bg-[#11161F] hover:bg-[#161D28] border border-white/[0.08] rounded-lg transition-colors whitespace-nowrap"
        >
          <RotateCcw className="w-3.5 h-3.5 shrink-0" />
          <span>Réinitialiser le flux et la mémoire</span>
        </button>
      </div>

      {/* Quick Templates */}
      <div className="bg-[#11161F] border border-white/[0.08] rounded-xl p-5 space-y-3">
        <div className="text-xs font-medium text-slate-300">
          Modèles de session prêts à l&apos;emploi
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
          {SESSION_TEMPLATES.map((tpl) => {
            const isSelected = config.name === tpl.config.name;
            return (
              <button
                key={tpl.id}
                type="button"
                onClick={() => onChange({ ...tpl.config })}
                className={`text-left p-3.5 rounded-lg border transition-colors ${
                  isSelected
                    ? 'bg-cyan-500/10 border-cyan-500/40 text-cyan-200'
                    : 'bg-[#0D1118] border-white/[0.07] text-slate-300 hover:border-white/[0.15]'
                }`}
              >
                <div className="text-xs font-semibold truncate">{tpl.label}</div>
                <div className="text-[11px] text-slate-400 mt-1 truncate">
                  {tpl.config.level} · {tpl.config.durationMinutes} min · {tpl.config.participantsCount} apprenants
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Configurable Fields */}
      <div className="bg-[#11161F] border border-white/[0.08] rounded-xl p-6 space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-slate-300">Nom de la formation</span>
            <input
              type="text"
              value={config.name}
              onChange={(e) => updateField('name', e.target.value)}
              className="w-full px-3.5 py-2.5 text-sm text-slate-100 bg-[#0A0D12] border border-white/[0.1] rounded-lg focus:outline-none focus:border-cyan-400/70"
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-slate-300">Sujet du cours en cours</span>
            <input
              type="text"
              value={config.topic}
              onChange={(e) => updateField('topic', e.target.value)}
              className="w-full px-3.5 py-2.5 text-sm text-slate-100 bg-[#0A0D12] border border-white/[0.1] rounded-lg focus:outline-none focus:border-cyan-400/70"
            />
          </label>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          <div className="space-y-1.5">
            <span className="text-xs font-medium text-slate-300">Niveau des apprenants</span>
            <div className="grid grid-cols-2 gap-1.5">
              {LEVELS.map((lvl) => (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => updateField('level', lvl)}
                  className={`px-3 py-2 text-xs font-medium rounded-lg border transition-colors ${
                    config.level === lvl
                      ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40'
                      : 'bg-[#0A0D12] text-slate-400 border-white/[0.08] hover:text-slate-200'
                  }`}
                >
                  {lvl}
                </button>
              ))}
            </div>
          </div>

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-slate-300">Nombre de participants</span>
            <input
              type="number"
              min={1}
              max={500}
              value={config.participantsCount}
              onChange={(e) =>
                updateField('participantsCount', Math.max(1, Number(e.target.value) || 1))
              }
              className="w-full px-3.5 py-2.5 text-sm font-mono tabular-nums text-slate-100 bg-[#0A0D12] border border-white/[0.1] rounded-lg focus:outline-none focus:border-cyan-400/70"
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-slate-300">Durée de la session (min)</span>
            <input
              type="number"
              min={10}
              max={480}
              step={5}
              value={config.durationMinutes}
              onChange={(e) =>
                updateField('durationMinutes', Math.max(10, Number(e.target.value) || 60))
              }
              className="w-full px-3.5 py-2.5 text-sm font-mono tabular-nums text-slate-100 bg-[#0A0D12] border border-white/[0.1] rounded-lg focus:outline-none focus:border-cyan-400/70"
            />
          </label>
        </div>

        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-slate-300">Objectifs pédagogiques</span>
          <textarea
            rows={3}
            value={config.objectives}
            onChange={(e) => updateField('objectives', e.target.value)}
            className="w-full px-3.5 py-2.5 text-sm text-slate-100 bg-[#0A0D12] border border-white/[0.1] rounded-lg focus:outline-none focus:border-cyan-400/70 resize-y"
          />
        </label>

        <div className="pt-2 border-t border-white/[0.06] flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-0.5">
            <div className="text-xs font-medium text-slate-300">
              Cooldown entre deux propositions automatiques
            </div>
            <p className="text-xs text-slate-500">
              Évite la surcharge cognitive en espaçant les suggestions spontanées (sauf sollicitation directe).
            </p>
          </div>
          <div className="flex items-center gap-2">
            {[10, 20, 30, 45].map((sec) => (
              <button
                key={sec}
                type="button"
                onClick={() => updateField('cooldownSeconds', sec)}
                className={`px-3 py-1.5 text-xs font-mono tabular-nums rounded-lg border transition-colors ${
                  config.cooldownSeconds === sec
                    ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40'
                    : 'bg-[#0A0D12] text-slate-400 border-white/[0.08] hover:text-slate-200'
                }`}
              >
                {sec} s
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
