import { useState, type FormEvent } from 'react';
import { Mic, MicOff, Radio, Send, Square } from 'lucide-react';
import type {
  AudioDeviceOption,
  CaptureMode,
} from '../services/neo/audioInputAdapter';
import type {
  ExchangeCategory,
  NeoMode,
  SpeakerRole,
  TranscriptExchange,
} from '../services/neo/types';

interface ExchangeStreamProps {
  exchanges: TranscriptExchange[];
  mode: NeoMode;
  isBusy: boolean;
  isTranscribing: boolean;
  micActive: boolean;
  micSupported: boolean;
  micError: string | null;
  audioLevel: number;
  captureMode: CaptureMode;
  manualRecording: boolean;
  devices: AudioDeviceOption[];
  selectedDeviceId: string;
  onSelectDevice: (deviceId: string) => void;
  onChangeCaptureMode: (captureMode: CaptureMode) => void;
  onToggleMic: () => void;
  onToggleManualRecord: () => void;
  onSubmitUtterance: (speaker: SpeakerRole, text: string) => void;
}

const FILTER_OPTIONS: Array<'Tous' | ExchangeCategory> = [
  'Tous',
  'Question',
  'Incompréhension',
  'Confusion',
  'Répétition',
  "Demande d'exemple",
  'Hors sujet',
];

const CATEGORY_TEXT_COLOR: Record<ExchangeCategory, string> = {
  Question: 'text-cyan-400',
  Incompréhension: 'text-rose-400',
  Confusion: 'text-amber-400',
  Répétition: 'text-amber-300',
  "Demande d'exemple": 'text-cyan-300',
  'Hors sujet': 'text-slate-500',
  'Échange normal': 'text-emerald-400',
};

export function ExchangeStream({
  exchanges,
  mode,
  isBusy,
  isTranscribing,
  micActive,
  micSupported,
  micError,
  audioLevel,
  captureMode,
  manualRecording,
  devices,
  selectedDeviceId,
  onSelectDevice,
  onChangeCaptureMode,
  onToggleMic,
  onToggleManualRecord,
  onSubmitUtterance,
}: ExchangeStreamProps) {
  const [filter, setFilter] = useState<'Tous' | ExchangeCategory>('Tous');
  const [speaker, setSpeaker] = useState<SpeakerRole>('Apprenant');
  const [inputText, setInputText] = useState('');

  const filteredExchanges =
    filter === 'Tous' ? exchanges : exchanges.filter((ex) => ex.category === filter);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = inputText.trim();
    if (!trimmed || isBusy || mode === 'OFF') return;
    onSubmitUtterance(speaker, trimmed);
    setInputText('');
  };

  return (
    <section
      aria-label="Analyse pédagogique en temps réel"
      className="flex flex-col bg-[#11161F] border border-white/[0.08] rounded-xl overflow-hidden"
    >
      {/* Header + Filter Bar */}
      <div className="px-5 py-4 border-b border-white/[0.06] space-y-3">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-slate-100 tracking-tight">
              Analyse pédagogique en temps réel
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Capture microphone, transcription audio et catégorisation contextuelle
            </p>
          </div>
          <span className="text-xs font-mono text-slate-400 tabular-nums shrink-0">
            {exchanges.length} échange{exchanges.length > 1 ? 's' : ''}
          </span>
        </div>

        <div
          className="flex items-center gap-1 overflow-x-auto pb-0.5"
          role="tablist"
          aria-label="Filtrer les échanges par catégorie"
        >
          {FILTER_OPTIONS.map((option) => {
            const active = filter === option;
            return (
              <button
                key={option}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(option)}
                className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors whitespace-nowrap shrink-0 ${
                  active
                    ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04] border border-transparent'
                }`}
              >
                {option}
              </button>
            );
          })}
        </div>
      </div>

      {/* Live Stream List */}
      <div className="flex-1 min-h-[280px] max-h-[400px] overflow-y-auto divide-y divide-white/[0.06]">
        {filteredExchanges.length === 0 ? (
          <div className="py-12 px-6 text-center space-y-2">
            <p className="text-sm font-medium text-slate-300">
              {exchanges.length === 0
                ? 'En attente de prise de parole'
                : 'Aucun échange dans cette catégorie'}
            </p>
            <p className="text-xs text-slate-500 max-w-md mx-auto">
              Activez le microphone ci-dessous pour capter et transcrire les échanges de votre
              session en direct, ou saisissez une phrase manuellement.
            </p>
          </div>
        ) : (
          filteredExchanges.map((ex) => (
            <article key={ex.id} className="px-5 py-3.5 hover:bg-white/[0.015] transition-colors">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400 tabular-nums">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-slate-400">{ex.timestamp}</span>
                  <span aria-hidden="true">·</span>
                  <span
                    className={`font-medium ${
                      ex.speaker === 'Formateur' ? 'text-slate-200' : 'text-slate-300'
                    }`}
                  >
                    {ex.speaker}
                  </span>
                  <span aria-hidden="true">·</span>
                  <span className={`font-semibold ${CATEGORY_TEXT_COLOR[ex.category]}`}>
                    {ex.category}
                  </span>
                  <span aria-hidden="true">·</span>
                  <span className="text-slate-500">Priorité {ex.priority}</span>
                </div>
                <span className="font-mono text-[11px] text-slate-500">
                  {ex.origin === 'micro' ? 'Microphone' : 'Saisie'}
                </span>
              </div>

              <p className="mt-1.5 text-sm text-slate-100 leading-relaxed">{ex.text}</p>

              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
                {ex.contextInsights.length > 0 && (
                  <span className="text-amber-300/90">
                    Contexte : {ex.contextInsights.join(' · ')}
                  </span>
                )}
                <span className="text-slate-500">Décision : {ex.decisionSummary}</span>
              </div>
            </article>
          ))
        )}

        {isTranscribing && (
          <div className="px-5 py-3 bg-cyan-500/[0.05] text-xs text-cyan-300">
            Transcription de l&apos;audio capté en cours…
          </div>
        )}
      </div>

      {/* Real Microphone & Direct Input Console */}
      <div className="p-4 bg-[#0D1118] border-t border-white/[0.06] space-y-3.5">
        {/* Microphone Controls */}
        <div className="space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={onToggleMic}
                disabled={!micSupported || mode === 'OFF'}
                className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-lg border transition-colors whitespace-nowrap ${
                  micActive
                    ? 'bg-rose-500/15 text-rose-300 border-rose-500/35 hover:bg-rose-500/25'
                    : 'bg-cyan-500 text-slate-950 border-cyan-500 hover:bg-cyan-400 disabled:opacity-40 disabled:cursor-not-allowed'
                }`}
              >
                {micActive ? (
                  <>
                    <MicOff className="w-3.5 h-3.5 shrink-0" />
                    <span>Couper le micro</span>
                  </>
                ) : (
                  <>
                    <Mic className="w-3.5 h-3.5 shrink-0" />
                    <span>Activer le micro</span>
                  </>
                )}
              </button>

              {micActive && (
                <div className="flex items-center gap-1 p-0.5 bg-[#11161F] border border-white/[0.08] rounded-lg">
                  <button
                    type="button"
                    onClick={() => onChangeCaptureMode('vad')}
                    className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                      captureMode === 'vad'
                        ? 'bg-cyan-500/20 text-cyan-300'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Détection auto (VAD)
                  </button>
                  <button
                    type="button"
                    onClick={() => onChangeCaptureMode('manual')}
                    className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                      captureMode === 'manual'
                        ? 'bg-cyan-500/20 text-cyan-300'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Capture manuelle
                  </button>
                </div>
              )}

              {micActive && captureMode === 'manual' && (
                <button
                  type="button"
                  onClick={onToggleManualRecord}
                  disabled={isBusy || isTranscribing}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors whitespace-nowrap ${
                    manualRecording
                      ? 'bg-amber-500 text-slate-950 border-amber-400'
                      : 'bg-white/[0.06] text-slate-100 border-white/[0.12] hover:border-cyan-400/50'
                  }`}
                >
                  {manualRecording ? (
                    <>
                      <Square className="w-3 h-3 fill-current shrink-0" />
                      <span>Terminer &amp; analyser</span>
                    </>
                  ) : (
                    <>
                      <Radio className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                      <span>Enregistrer une phrase</span>
                    </>
                  )}
                </button>
              )}
            </div>

            {devices.length > 0 && (
              <select
                value={selectedDeviceId}
                onChange={(e) => onSelectDevice(e.target.value)}
                aria-label="Sélectionner le périphérique microphone"
                className="max-w-[210px] px-2.5 py-1.5 text-xs text-slate-300 bg-[#11161F] border border-white/[0.08] rounded-lg focus:outline-none focus:border-cyan-400/70 truncate"
              >
                {devices.map((d) => (
                  <option key={d.deviceId} value={d.deviceId}>
                    {d.label}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Live Microphone Signal Meter */}
          {micActive && (
            <div className="flex items-center gap-3 text-xs text-slate-400">
              <span className="whitespace-nowrap">Signal audio :</span>
              <div className="flex-1 h-1.5 bg-[#0A0D12] rounded-full overflow-hidden border border-white/[0.06]">
                <div
                  className="h-full bg-cyan-400 transition-all duration-75"
                  style={{ width: `${Math.round(audioLevel * 100)}%` }}
                />
              </div>
              <span className="font-mono tabular-nums w-10 text-right">
                {Math.round(audioLevel * 100)} %
              </span>
            </div>
          )}

          {micError && <p className="text-xs text-rose-400">{micError}</p>}
        </div>

        {/* Manual Text Entry + Speaker Selector */}
        <form onSubmit={handleSubmit} className="pt-2.5 border-t border-white/[0.06] space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-slate-400">Locuteur attribué :</span>
            <div className="flex items-center gap-1 p-0.5 bg-[#11161F] border border-white/[0.08] rounded-lg">
              {(['Apprenant', 'Formateur'] as SpeakerRole[]).map((role) => (
                <button
                  key={role}
                  type="button"
                  onClick={() => setSpeaker(role)}
                  className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                    speaker === role
                      ? 'bg-white/[0.1] text-white'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {role}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              disabled={isBusy || mode === 'OFF'}
              placeholder={`Saisir une phrase entendue (${speaker}) pour analyse immédiate…`}
              aria-label="Saisir une phrase de cours à analyser par NÉO"
              className="flex-1 min-w-0 px-3.5 py-2.5 text-xs text-slate-100 placeholder:text-slate-500 bg-[#0A0D12] border border-white/[0.1] rounded-lg focus:outline-none focus:border-cyan-400/70 disabled:opacity-40"
            />
            <button
              type="submit"
              disabled={isBusy || mode === 'OFF' || !inputText.trim()}
              className="flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium rounded-lg bg-white/[0.08] text-slate-100 hover:bg-white/[0.14] border border-white/[0.1] transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap shrink-0"
            >
              <Send className="w-3.5 h-3.5 shrink-0" />
              <span>Analyser</span>
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
