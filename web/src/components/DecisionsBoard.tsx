import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type DecisionSummary } from '../api/client';
import { useBrainStore } from '../store/brainStore';
import {
  FileText,
  Flag,
  GitBranch,
  CheckCircle,
  HelpCircle,
  Loader2,
  Calendar,
  X,
  AlertTriangle,
} from 'lucide-react';

interface DecisionsBoardProps {
  onToast?: (message: string, type?: 'success' | 'info' | 'warning') => void;
}

export const DecisionsBoard: React.FC<DecisionsBoardProps> = ({ onToast }) => {
  const queryClient = useQueryClient();
  const mergeGraph = useBrainStore((state) => state.mergeGraph);
  const setHighlight = useBrainStore((state) => state.setHighlight);
  const setSelectedNodeId = useBrainStore((state) => state.setSelectedNodeId);
  const setRightTab = useBrainStore((state) => state.setRightTab);

  const [flagModalDecision, setFlagModalDecision] = useState<DecisionSummary | null>(null);
  const [flagNote, setFlagNote] = useState('');
  const [tracingId, setTracingId] = useState<string | null>(null);

  // Fetch all decisions ordered by drift_count desc
  const { data: decisions, isLoading, error } = useQuery<DecisionSummary[]>({
    queryKey: ['decisions'],
    queryFn: () => api.getDecisions(),
    refetchInterval: 10000,
  });

  // Trace decision mutation
  const traceMutation = useMutation({
    mutationFn: (id: string) => api.traceDecision(id),
    onSuccess: (data, id) => {
      mergeGraph(data.graph);
      const nodeIds = data.graph.nodes.map((n) => n.id);
      const edgeIds = data.graph.edges.map((e) => e.id);
      setHighlight({ node_ids: nodeIds, edge_ids: edgeIds });
      setSelectedNodeId(id);
      onToast?.(`Traced decision ${id}: provenance path highlighted on graph.`, 'info');
    },
    onError: (err: Error) => {
      onToast?.(`Trace failed: ${err.message}`, 'warning');
    },
    onSettled: () => {
      setTracingId(null);
    },
  });

  // Flag for review mutation
  const flagMutation = useMutation({
    mutationFn: (vars: { id: string; note: string }) => api.flagDecision(vars.id, vars.note),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['reviews'] });
      setFlagModalDecision(null);
      setFlagNote('');
      if (data.already_open) {
        onToast?.('A review request is already open for this decision.', 'info');
      } else {
        onToast?.(`Flagged for review! Created ${data.review_request_id}.`, 'success');
        setRightTab('reviews');
      }
    },
    onError: (err: Error) => {
      onToast?.(`Flagging failed: ${err.message}`, 'warning');
    },
  });

  const handleTrace = (id: string) => {
    setTracingId(id);
    traceMutation.mutate(id);
  };

  const openFlagModal = (dec: DecisionSummary) => {
    setFlagModalDecision(dec);
    setFlagNote(`Architectural drift detected: ${dec.drift_count} changes require review.`);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin text-emerald-400" />
        <span className="text-xs font-mono">Loading decisions board...</span>
      </div>
    );
  }

  if (error || !decisions) {
    return (
      <div className="p-4 text-xs text-rose-400 bg-rose-950/20 border border-rose-900 rounded-xl m-4">
        Failed to load decisions from knowledge graph.
      </div>
    );
  }

  const getFreshnessBadge = (freshness: string) => {
    switch (freshness) {
      case 'fresh':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono font-medium bg-emerald-950/60 text-emerald-400 border border-emerald-800/80">
            <CheckCircle className="w-3 h-3 text-emerald-400" />
            <span>fresh</span>
          </span>
        );
      case 'stale':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono font-medium bg-amber-950/60 text-amber-300 border border-amber-800/80 animate-pulse">
            <AlertTriangle className="w-3 h-3 text-amber-400" />
            <span>stale</span>
          </span>
        );
      case 'superseded':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono font-medium bg-slate-800 text-slate-400 border border-slate-700">
            <HelpCircle className="w-3 h-3" />
            <span>superseded</span>
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900/40">
      {/* Top summary header */}
      <div className="p-3 border-b border-slate-800 bg-slate-900/70 flex items-center justify-between text-xs font-mono">
        <div className="flex items-center gap-2 text-slate-300">
          <FileText className="w-3.5 h-3.5 text-rose-400" />
          <span>{decisions.length} Architecture Decisions</span>
        </div>
        <span className="text-slate-400">Ordered by drift</span>
      </div>

      {/* Decisions List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {decisions.map((dec) => {
          const dateStr = new Date(dec.decided_at * 1000).toISOString().split('T')[0];

          return (
            <div
              key={dec.id}
              className="p-3.5 rounded-xl bg-slate-850/80 border border-slate-800 hover:border-slate-750 transition-all shadow-sm space-y-2.5"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="font-mono text-[11px] text-slate-400 select-all font-medium">
                  {dec.id}
                </span>
                {getFreshnessBadge(dec.freshness)}
              </div>

              <h4 className="text-xs font-semibold text-slate-200 leading-snug">
                {dec.title}
              </h4>

              {/* Metrics Row */}
              <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 pt-1 border-t border-slate-800/60">
                <div className="flex items-center gap-1">
                  <Calendar className="w-3 h-3 text-slate-500" />
                  <span>{dateStr}</span>
                </div>

                <div className="flex items-center gap-1.5">
                  <span>Drift:</span>
                  <span
                    className={`font-semibold ${
                      dec.drift_count > 0 ? 'text-amber-400' : 'text-slate-400'
                    }`}
                  >
                    {dec.drift_count} changes
                  </span>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-2 pt-2">
                <button
                  onClick={() => handleTrace(dec.id)}
                  disabled={tracingId === dec.id}
                  className="flex-1 flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-750 text-slate-200 text-xs font-mono font-medium transition-colors border border-slate-700/80 disabled:opacity-50"
                  title="Trace decision provenance chain on graph"
                >
                  {tracingId === dec.id ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <GitBranch className="w-3 h-3 text-sky-400" />
                  )}
                  <span>Trace Path</span>
                </button>

                <button
                  onClick={() => openFlagModal(dec)}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 text-xs font-mono font-medium transition-colors border border-rose-500/30"
                  title="Flag this decision for architecture review"
                >
                  <Flag className="w-3 h-3 text-rose-400" />
                  <span>Flag</span>
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Flag Modal */}
      {flagModalDecision && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-md p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Flag className="w-4 h-4 text-rose-400" />
                <h3 className="text-sm font-semibold text-slate-100">Flag Decision for Review</h3>
              </div>
              <button
                onClick={() => setFlagModalDecision(null)}
                className="text-slate-400 hover:text-white p-1 rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="text-xs space-y-1">
              <p className="text-slate-400 font-mono">Decision ID: {flagModalDecision.id}</p>
              <p className="text-slate-200 font-medium">{flagModalDecision.title}</p>
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1.5">
                Review Note (max 300 chars):
              </label>
              <textarea
                value={flagNote}
                maxLength={300}
                onChange={(e) => setFlagNote(e.target.value)}
                rows={3}
                className="w-full bg-slate-850 border border-slate-700 rounded-lg p-2.5 text-xs text-slate-100 font-sans focus:outline-none focus:border-rose-500"
              />
              <span className="text-[10px] text-slate-500 font-mono float-right">
                {flagNote.length}/300
              </span>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setFlagModalDecision(null)}
                className="px-3.5 py-1.5 rounded-lg text-xs font-mono text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() =>
                  flagMutation.mutate({
                    id: flagModalDecision.id,
                    note: flagNote,
                  })
                }
                disabled={flagMutation.isPending || !flagNote.trim()}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium font-mono bg-rose-600 hover:bg-rose-500 text-white font-semibold transition-colors shadow-sm disabled:opacity-50"
              >
                {flagMutation.isPending ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Flag className="w-3.5 h-3.5" />
                )}
                <span>Create Review Request</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
