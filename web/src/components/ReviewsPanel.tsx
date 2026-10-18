import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, type ReviewRequestOut } from '../api/client';
import { useBrainStore } from '../store/brainStore';
import { CheckSquare, User, Loader2, Calendar } from 'lucide-react';

export const ReviewsPanel: React.FC = () => {
  const setSelectedNodeId = useBrainStore((state) => state.setSelectedNodeId);
  const setRightTab = useBrainStore((state) => state.setRightTab);

  const { data: reviews, isLoading, error } = useQuery<ReviewRequestOut[]>({
    queryKey: ['reviews'],
    queryFn: () => api.getReviews(),
    refetchInterval: 10000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin text-emerald-400" />
        <span className="text-xs font-mono">Loading review requests...</span>
      </div>
    );
  }

  if (error || !reviews) {
    return (
      <div className="p-4 text-xs text-rose-400 bg-rose-950/20 border border-rose-900 rounded-xl m-4">
        Failed to load review requests.
      </div>
    );
  }

  if (reviews.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center text-slate-500">
        <CheckSquare className="w-10 h-10 mb-3 text-slate-600 opacity-60" />
        <p className="text-sm font-medium text-slate-400">No Review Requests</p>
        <p className="text-xs text-slate-600 mt-1 max-w-xs">
          Decisions flagged by the agent or manually will be queued here for assigned tech leads and deciders.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-slate-900/40">
      {/* Top summary header */}
      <div className="p-3 border-b border-slate-800 bg-slate-900/70 flex items-center justify-between text-xs font-mono">
        <div className="flex items-center gap-2 text-slate-300">
          <CheckSquare className="w-3.5 h-3.5 text-pink-400" />
          <span>{reviews.length} Active Review Requests</span>
        </div>
        <span className="text-slate-400">Ordered by date</span>
      </div>

      {/* Reviews List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {reviews.map((rev) => {
          const dateStr = new Date(rev.created_at * 1000).toISOString().split('T')[0];

          return (
            <div
              key={rev.id}
              className="p-3.5 rounded-xl bg-slate-850/80 border border-slate-800 hover:border-slate-750 transition-all shadow-sm space-y-2.5"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] text-pink-400 font-semibold select-all">
                  {rev.id}
                </span>

                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-medium border ${
                    rev.status === 'open'
                      ? 'bg-amber-950/60 border-amber-800 text-amber-300'
                      : 'bg-slate-800 border-slate-700 text-slate-400'
                  }`}
                >
                  {rev.status}
                </span>
              </div>

              {/* Target Decision Link */}
              <div>
                <span className="text-[10px] font-mono uppercase text-slate-500 tracking-wider">
                  Target Decision:
                </span>
                <button
                  onClick={() => {
                    setSelectedNodeId(rev.decision_id);
                    setRightTab('node');
                  }}
                  className="block text-left text-xs font-semibold text-slate-200 hover:text-emerald-400 transition-colors mt-0.5"
                >
                  {rev.decision} ({rev.decision_id})
                </button>
              </div>

              {/* Note Content */}
              <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800/80 text-xs text-slate-300 font-sans leading-relaxed">
                {rev.note}
              </div>

              {/* Meta details footer */}
              <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 pt-1 border-t border-slate-800/60">
                <div className="flex items-center gap-1">
                  <Calendar className="w-3 h-3 text-slate-500" />
                  <span>{dateStr}</span>
                </div>

                {rev.assignee_ids && rev.assignee_ids.length > 0 && (
                  <div className="flex items-center gap-1 text-slate-300">
                    <User className="w-3 h-3 text-sky-400" />
                    <span>{rev.assignee_ids.join(', ')}</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
