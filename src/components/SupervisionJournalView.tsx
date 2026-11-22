import { useState } from 'react';
import { Search } from 'lucide-react';
import type { EventLogEntry, SessionMetrics } from '../services/neo/types';

interface SupervisionJournalViewProps {
  logs: EventLogEntry[];
  metrics: SessionMetrics;
}

export function SupervisionJournalView({ logs, metrics }: SupervisionJournalViewProps) {
  const [query, setQuery] = useState('');

  const filteredLogs = logs.filter((item) => {
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return (
      item.transcript.toLowerCase().includes(q) ||
      item.eventType.toLowerCase().includes(q) ||
      item.analysis.toLowerCase().includes(q) ||
      item.decision.toLowerCase().includes(q) ||
      item.proposedIntervention.toLowerCase().includes(q)
    );
  });

  const avgSec =
    metrics.avgResponseMs > 0 ? `${(metrics.avgResponseMs / 1000).toFixed(2)} s` : '—';

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-white tracking-tight">
            Journal de supervision &amp; métriques de session
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Traçabilité complète des échanges analysés, décisions de silence et interventions proposées.
          </p>
        </div>

        <div className="relative w-full sm:w-72">
          <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filtrer le journal…"
            aria-label="Filtrer le journal des événements"
            className="w-full pl-9 pr-3.5 py-2 text-xs text-slate-100 placeholder:text-slate-500 bg-[#11161F] border border-white/[0.08] rounded-lg focus:outline-none focus:border-cyan-400/70"
          />
        </div>
      </div>

      {/* 5 Real Computed Counters */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <div className="bg-[#11161F] border border-white/[0.08] rounded-xl p-4 space-y-1">
          <div className="text-xs text-slate-400">Questions posées</div>
          <div className="text-2xl font-semibold font-mono tabular-nums text-white">
            {metrics.questionsCount}
          </div>
        </div>
        <div className="bg-[#11161F] border border-white/[0.08] rounded-xl p-4 space-y-1">
          <div className="text-xs text-slate-400">Incompréhensions détectées</div>
          <div className="text-2xl font-semibold font-mono tabular-nums text-rose-400">
            {metrics.misunderstandingsCount}
          </div>
        </div>
        <div className="bg-[#11161F] border border-white/[0.08] rounded-xl p-4 space-y-1">
          <div className="text-xs text-slate-400">Interventions proposées</div>
          <div className="text-2xl font-semibold font-mono tabular-nums text-cyan-400">
            {metrics.proposalsCount}
          </div>
        </div>
        <div className="bg-[#11161F] border border-white/[0.08] rounded-xl p-4 space-y-1">
          <div className="text-xs text-slate-400">Interventions ignorées</div>
          <div className="text-2xl font-semibold font-mono tabular-nums text-slate-300">
            {metrics.ignoredCount}
          </div>
        </div>
        <div className="bg-[#11161F] border border-white/[0.08] rounded-xl p-4 space-y-1 col-span-2 sm:col-span-1">
          <div className="text-xs text-slate-400">Temps moyen de réponse</div>
          <div className="text-2xl font-semibold font-mono tabular-nums text-emerald-400">
            {avgSec}
          </div>
        </div>
      </div>

      {/* Event Log Table */}
      <div className="bg-[#11161F] border border-white/[0.08] rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-white/[0.08] text-slate-400 bg-[#0D1118]">
                <th className="py-3 px-4 font-medium whitespace-nowrap">Heure</th>
                <th className="py-3 px-4 font-medium whitespace-nowrap">Type</th>
                <th className="py-3 px-4 font-medium min-w-[220px]">Transcription</th>
                <th className="py-3 px-4 font-medium min-w-[180px]">Analyse</th>
                <th className="py-3 px-4 font-medium min-w-[180px]">Décision</th>
                <th className="py-3 px-4 font-medium min-w-[200px]">Intervention proposée</th>
                <th className="py-3 px-4 font-medium text-right whitespace-nowrap">Latence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.06]">
              {filteredLogs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 px-4 text-center text-slate-500">
                    Aucun événement enregistré dans le journal pour le moment.
                  </td>
                </tr>
              ) : (
                filteredLogs.map((row) => (
                  <tr key={row.id} className="hover:bg-white/[0.02] align-top">
                    <td className="py-3 px-4 font-mono tabular-nums text-slate-400 whitespace-nowrap">
                      {row.time}
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap font-medium text-slate-200">
                      {row.eventType}
                    </td>
                    <td className="py-3 px-4 text-slate-200 leading-relaxed">
                      <span className="text-slate-400 font-medium">{row.speaker} : </span>
                      {row.transcript}
                    </td>
                    <td className="py-3 px-4 text-slate-300 leading-relaxed">{row.analysis}</td>
                    <td className="py-3 px-4 text-slate-400 leading-relaxed">{row.decision}</td>
                    <td className="py-3 px-4 text-cyan-300/90 leading-relaxed">
                      {row.proposedIntervention || '—'}
                    </td>
                    <td className="py-3 px-4 text-right font-mono tabular-nums text-slate-400 whitespace-nowrap">
                      {row.latencyMs} ms
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
