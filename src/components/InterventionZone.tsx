import { useState, type FormEvent } from 'react';
import {
  Check,
  Copy,
  Expand,
  MonitorUp,
  RefreshCw,
  Send,
  ShieldAlert,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react';
import type { NeoMode, NeoProposal, NeoState, SessionMemory } from '../services/neo/types';

interface InterventionZoneProps {
  neoState: NeoState;
  mode: NeoMode;
  proposal: NeoProposal | null;
  lastSilenceReason: string | null;
  isBusy: boolean;
  isSpeaking: boolean;
  isGeneratingVoice: boolean;
  errorMsg: string | null;
  sessionMemory: SessionMemory;
  cooldownRemainingSec: number;
  onAccept: (proposal: NeoProposal) => void;
  onIgnore: (proposal: NeoProposal) => void;
  onReformulate: (proposal: NeoProposal) => void;
  onDevelop: (proposal: NeoProposal) => void;
  onSendToScreen: (proposal: NeoProposal) => void;
  onSpeakProposal: (proposal: NeoProposal) => void;
  onStopVoice: () => void;
  onDirectCommand: (command: string, actionType: string) => void;
}

const DIRECT_COMMANDS = [
  { label: '« Néo, reformule. »', action: 'reformulate' },
  { label: '« Néo, donne un exemple. »', action: 'example' },
  { label: '« Néo, explique plus simplement. »', action: 'simplify' },
  { label: '« Néo, résume. »', action: 'summarize' },
  { label: '« Néo, approfondis. »', action: 'deepen' },
  { label: '« Néo, répond à cette question. »', action: 'answer_last' },
];

export function InterventionZone({
  neoState,
  mode,
  proposal,
  lastSilenceReason,
  isBusy,
  isSpeaking,
  isGeneratingVoice,
  errorMsg,
  sessionMemory,
  cooldownRemainingSec,
  onAccept,
  onIgnore,
  onReformulate,
  onDevelop,
  onSendToScreen,
  onSpeakProposal,
  onStopVoice,
  onDirectCommand,
}: InterventionZoneProps) {
  const [freeCommand, setFreeCommand] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [showMemory, setShowMemory] = useState(false);

  const handleCopy = async (item: NeoProposal) => {
    try {
      await navigator.clipboard.writeText(`${item.title}\n\n${item.content}`);
      setCopiedId(item.id);
      setTimeout(() => setCopiedId((prev) => (prev === item.id ? null : prev)), 1800);
    } catch {
      setCopiedId(item.id);
      setTimeout(() => setCopiedId((prev) => (prev === item.id ? null : prev)), 1800);
    }
  };

  const handleSubmitCommand = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = freeCommand.trim();
    if (!trimmed || isBusy || mode === 'OFF') return;
    onDirectCommand(trimmed, 'libre');
    setFreeCommand('');
  };

  const memoryCount =
    sessionMemory.resolvedTopics.length +
    sessionMemory.persistentDifficulties.length +
    sessionMemory.confusedPairs.length;

  return (
    <section
      aria-label="Zone d'intervention de NÉO"
      className="flex flex-col bg-[#11161F] border border-white/[0.08] rounded-xl overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-white/[0.06]">
        <div>
          <h2 className="text-base font-semibold text-slate-100 tracking-tight">
            Zone d&apos;intervention pédagogique
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Propositions courtes, exploitables à l&apos;oral ou par la voix de NÉO
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowMemory((v) => !v)}
          className="px-3 py-1.5 text-xs font-medium text-slate-300 hover:text-cyan-300 bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.08] rounded-lg transition-colors whitespace-nowrap shrink-0 tabular-nums"
        >
          Mémoire ({memoryCount})
        </button>
      </div>

      {/* Collapsible Session Memory Drawer */}
      {showMemory && (
        <div className="px-5 py-3.5 bg-[#0D1118] border-b border-white/[0.06] text-xs space-y-2">
          <div className="font-medium text-slate-300">
            Mémoire pédagogique de session (anti-répétition)
          </div>
          {memoryCount === 0 ? (
            <p className="text-slate-500">
              Aucun concept résolu ou difficulté persistante enregistré pour le moment.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-1.5 text-slate-400">
              {sessionMemory.resolvedTopics.length > 0 && (
                <div>
                  <span className="text-emerald-400 font-medium">Notions traitées : </span>
                  {sessionMemory.resolvedTopics.join(' · ')}
                </div>
              )}
              {sessionMemory.persistentDifficulties.length > 0 && (
                <div>
                  <span className="text-amber-400 font-medium">Difficultés persistantes : </span>
                  {sessionMemory.persistentDifficulties.join(' · ')}
                </div>
              )}
              {sessionMemory.confusedPairs.length > 0 && (
                <div>
                  <span className="text-cyan-400 font-medium">Confusions suivies : </span>
                  {sessionMemory.confusedPairs.join(' · ')}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Main Proposal Area */}
      <div className="p-5 flex-1 flex flex-col gap-5">
        {errorMsg && (
          <div
            role="alert"
            className="flex items-start gap-2.5 p-3.5 rounded-lg bg-rose-500/10 border border-rose-500/25 text-xs text-rose-200"
          >
            <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <span>{errorMsg}</span>
          </div>
        )}

        {isBusy ? (
          <div className="py-10 px-4 flex flex-col items-center justify-center text-center gap-3 border border-white/[0.06] rounded-lg bg-[#0D1118]">
            <RefreshCw className="w-5 h-5 text-cyan-400 animate-spin" />
            <div className="space-y-1">
              <p className="text-sm font-medium text-slate-200">
                Analyse pédagogique en cours…
              </p>
              <p className="text-xs text-slate-400">
                Vérification du contexte de session, du niveau et de la priorité d&apos;intervention
              </p>
            </div>
          </div>
        ) : proposal ? (
          <div className="space-y-4">
            {/* Unboxed Metadata + Voice Playback Trigger */}
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400 tabular-nums">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-cyan-400">{proposal.helpType}</span>
                <span aria-hidden="true">·</span>
                <span>Priorité {proposal.priority}</span>
                <span aria-hidden="true">·</span>
                <span>Confiance {proposal.confidence} %</span>
              </div>

              <button
                type="button"
                disabled={isGeneratingVoice}
                onClick={() => (isSpeaking ? onStopVoice() : onSpeakProposal(proposal))}
                className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md border transition-colors whitespace-nowrap ${
                  isSpeaking
                    ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                    : 'bg-white/[0.04] text-slate-200 border-white/[0.08] hover:text-cyan-300'
                }`}
              >
                {isSpeaking ? (
                  <>
                    <VolumeX className="w-3.5 h-3.5 shrink-0" />
                    <span>Arrêter voix</span>
                  </>
                ) : (
                  <>
                    <Volume2 className="w-3.5 h-3.5 shrink-0" />
                    <span>{isGeneratingVoice ? 'Synthèse…' : 'Voix de NÉO'}</span>
                  </>
                )}
              </button>
            </div>

            {/* Detected Issue & Origin */}
            <div className="space-y-2 pb-3 border-b border-white/[0.06]">
              <div className="text-xs font-medium text-slate-400">
                Problème détecté :{' '}
                <span className="text-slate-200 font-normal">{proposal.detectedIssue}</span>
              </div>
              <p className="text-xs text-slate-400 italic leading-relaxed">
                Origine ({proposal.originSpeaker}) : « {proposal.originQuote} »
              </p>
            </div>

            {/* Actionable Proposal */}
            <div className="space-y-2">
              <h3 className="text-base font-semibold text-white tracking-tight">
                {proposal.title}
              </h3>
              <p className="text-sm text-slate-200 leading-relaxed whitespace-pre-line">
                {proposal.content}
              </p>
            </div>

            {/* 6 Proposal Actions */}
            <div className="pt-2 grid grid-cols-2 sm:grid-cols-3 gap-2">
              <button
                type="button"
                onClick={() => onAccept(proposal)}
                className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-cyan-500 text-slate-950 hover:bg-cyan-400 transition-colors whitespace-nowrap"
              >
                <Check className="w-3.5 h-3.5 shrink-0" />
                <span>Accepter</span>
              </button>

              <button
                type="button"
                onClick={() => onIgnore(proposal)}
                className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-white/[0.04] text-slate-300 hover:bg-white/[0.08] border border-white/[0.08] transition-colors whitespace-nowrap"
              >
                <X className="w-3.5 h-3.5 shrink-0" />
                <span>Ignorer</span>
              </button>

              <button
                type="button"
                onClick={() => onReformulate(proposal)}
                className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-white/[0.04] text-slate-200 hover:bg-white/[0.08] border border-white/[0.08] transition-colors whitespace-nowrap"
              >
                <RefreshCw className="w-3.5 h-3.5 shrink-0" />
                <span>Reformuler</span>
              </button>

              <button
                type="button"
                onClick={() => onDevelop(proposal)}
                className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-white/[0.04] text-slate-200 hover:bg-white/[0.08] border border-white/[0.08] transition-colors whitespace-nowrap"
              >
                <Expand className="w-3.5 h-3.5 shrink-0" />
                <span>Développer</span>
              </button>

              <button
                type="button"
                onClick={() => handleCopy(proposal)}
                className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-white/[0.04] text-slate-200 hover:bg-white/[0.08] border border-white/[0.08] transition-colors whitespace-nowrap"
              >
                <Copy className="w-3.5 h-3.5 shrink-0" />
                <span>{copiedId === proposal.id ? 'Copié' : 'Copier'}</span>
              </button>

              <button
                type="button"
                onClick={() => onSendToScreen(proposal)}
                className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-cyan-500/15 text-cyan-300 hover:bg-cyan-500/25 border border-cyan-500/30 transition-colors whitespace-nowrap"
              >
                <MonitorUp className="w-3.5 h-3.5 shrink-0" />
                <span>Envoyer à l&apos;écran</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="py-8 px-5 border border-white/[0.06] rounded-lg bg-[#0D1118] space-y-2.5">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-200">
              <VolumeX className="w-4 h-4 text-slate-400 shrink-0" />
              <span>
                {mode === 'OFF'
                  ? 'Assistant désactivé'
                  : neoState === 'En veille'
                    ? 'NÉO en veille'
                    : 'Silence pédagogique actif'}
              </span>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              {mode === 'OFF'
                ? 'Activez un mode (ACTIF, PASSIF ou SUR DEMANDE) pour reprendre l’analyse pédagogique.'
                : lastSilenceReason
                  ? lastSilenceReason
                  : 'Aucune intervention requise pour le moment. NÉO n’intervient que lorsqu’une incompréhension, confusion ou question pertinente le justifie.'}
            </p>
            {cooldownRemainingSec > 0 && mode === 'ACTIF' && (
              <p className="text-xs font-mono text-amber-400 tabular-nums">
                Cooldown anti-intrusion en cours : {cooldownRemainingSec} s (contournable par sollicitation directe)
              </p>
            )}
          </div>
        )}

        {/* Direct Trainer Solicitations */}
        <div className="pt-3 border-t border-white/[0.06] space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-slate-300">
              Sollicitation directe du formateur (Priorité 1)
            </span>
            <span className="text-[11px] text-slate-500">Ignorer le cooldown</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {DIRECT_COMMANDS.map((cmd) => (
              <button
                key={cmd.action}
                type="button"
                disabled={isBusy || mode === 'OFF'}
                onClick={() => onDirectCommand(cmd.label, cmd.action)}
                className="text-left px-3 py-2 text-xs font-medium text-slate-200 bg-[#161D28] hover:bg-[#1C2533] hover:text-cyan-300 border border-white/[0.07] rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed truncate"
              >
                {cmd.label}
              </button>
            ))}
          </div>

          {/* Freeform Trainer Command Bar */}
          <form onSubmit={handleSubmitCommand} className="flex items-center gap-2 pt-1">
            <input
              type="text"
              value={freeCommand}
              onChange={(e) => setFreeCommand(e.target.value)}
              disabled={isBusy || mode === 'OFF'}
              placeholder="Commande libre à NÉO (ex : Donne une analogie avec un restaurant)..."
              aria-label="Champ de commande libre pour communiquer avec NÉO"
              className="flex-1 min-w-0 px-3.5 py-2.5 text-xs text-slate-100 placeholder:text-slate-500 bg-[#0A0D12] border border-white/[0.1] rounded-lg focus:outline-none focus:border-cyan-400/70 disabled:opacity-40"
            />
            <button
              type="submit"
              disabled={isBusy || mode === 'OFF' || !freeCommand.trim()}
              className="flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium rounded-lg bg-cyan-500 text-slate-950 hover:bg-cyan-400 transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap shrink-0"
            >
              <Send className="w-3.5 h-3.5 shrink-0" />
              <span>Solliciter</span>
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}
