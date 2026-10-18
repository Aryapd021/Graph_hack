import React, { useState } from 'react';
import { useBrainStore } from '../store/brainStore';
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, Clock, Terminal, Database } from 'lucide-react';

export const TracePanel: React.FC = () => {
  const latestTrace = useBrainStore((state) => state.latestTrace);
  const [expandedSteps, setExpandedSteps] = useState<Record<number, boolean>>({});

  const toggleStep = (stepNumber: number) => {
    setExpandedSteps((prev) => ({
      ...prev,
      [stepNumber]: !prev[stepNumber],
    }));
  };

  if (!latestTrace || latestTrace.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center text-slate-500">
        <Terminal className="w-10 h-10 mb-3 text-slate-600 opacity-60" />
        <p className="text-sm font-medium text-slate-400">No Tool Execution Trace Yet</p>
        <p className="text-xs text-slate-600 mt-1 max-w-xs">
          When the agent queries FalkorDB via MCP tools, every step, cypher query, argument, and latency will appear here.
        </p>
      </div>
    );
  }

  const totalDuration = latestTrace.reduce((sum, s) => sum + s.duration_ms, 0);

  return (
    <div className="flex flex-col h-full bg-slate-900/40">
      {/* Top summary stats */}
      <div className="p-3 border-b border-slate-800 bg-slate-900/70 flex items-center justify-between text-xs font-mono">
        <div className="flex items-center gap-2 text-slate-300">
          <Terminal className="w-3.5 h-3.5 text-emerald-400" />
          <span>{latestTrace.length} Tool Execution Rounds</span>
        </div>
        <div className="flex items-center gap-1.5 text-slate-400">
          <Clock className="w-3 h-3 text-sky-400" />
          <span>{totalDuration}ms total</span>
        </div>
      </div>

      {/* Steps Accordion List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {latestTrace.map((step) => {
          const isExpanded = !!expandedSteps[step.step];

          return (
            <div
              key={step.step}
              className="border border-slate-800 bg-slate-850/80 rounded-xl overflow-hidden shadow-sm transition-all"
            >
              {/* Step Header Accordion Toggle */}
              <button
                onClick={() => toggleStep(step.step)}
                className="w-full px-3.5 py-2.5 flex items-center justify-between text-left hover:bg-slate-800/50 transition-colors"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  {isExpanded ? (
                    <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />
                  )}

                  <span className="w-5 h-5 rounded-full bg-slate-800 border border-slate-700 text-xs font-mono text-slate-300 flex items-center justify-center shrink-0">
                    {step.step}
                  </span>

                  <span className="font-mono text-xs font-semibold text-emerald-400 truncate">
                    {step.tool}
                  </span>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <span className="font-mono text-[11px] text-slate-400">
                    {step.duration_ms}ms
                  </span>

                  {step.ok ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <XCircle className="w-4 h-4 text-rose-400" />
                  )}
                </div>
              </button>

              {/* Step Summary Row */}
              <div className="px-3.5 pb-2.5 pt-0">
                <p className="text-xs text-slate-300 leading-relaxed font-sans line-clamp-2">
                  {step.summary}
                </p>

                {/* Cypher Query Badges */}
                {step.cypher_ids && step.cypher_ids.length > 0 && (
                  <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                    <Database className="w-3 h-3 text-sky-400 shrink-0" />
                    {step.cypher_ids.map((qid) => (
                      <span
                        key={qid}
                        className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-sky-950/60 text-sky-300 border border-sky-800/50"
                        title={`Executed Cypher Query ${qid}`}
                      >
                        {qid}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Expanded JSON Arguments Details */}
              {isExpanded && (
                <div className="border-t border-slate-800/80 bg-slate-950/60 p-3 font-mono text-xs">
                  <div className="text-[11px] text-slate-500 mb-1 font-semibold uppercase tracking-wider">
                    Arguments:
                  </div>
                  <pre className="p-2 rounded bg-slate-900 border border-slate-800 text-slate-300 text-[11px] overflow-x-auto">
                    {JSON.stringify(step.args, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
