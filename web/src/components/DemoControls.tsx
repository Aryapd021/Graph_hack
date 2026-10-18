import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type ModuleSummary, type SimulatePRResponse } from '../api/client';
import { Play, RotateCcw, RefreshCw, X, Check, Loader2, Sparkles } from 'lucide-react';

interface DemoControlsProps {
  demoMode?: boolean;
  ingestRefresh?: boolean;
  onToast?: (message: string, type?: 'success' | 'info' | 'warning') => void;
}

export const DemoControls: React.FC<DemoControlsProps> = ({
  demoMode = true,
  ingestRefresh = true,
  onToast,
}) => {
  const queryClient = useQueryClient();
  const [showSimulateModal, setShowSimulateModal] = useState(false);
  const [selectedModule, setSelectedModule] = useState<string>('');
  const [prTitle, setPrTitle] = useState('Update telemetry and request handling');

  // Fetch codebase modules for the simulation dropdown
  const { data: modules } = useQuery<ModuleSummary[]>({
    queryKey: ['modules'],
    queryFn: () => api.getModules(),
    enabled: demoMode,
    staleTime: 60000,
  });

  // Default module selection when modules load
  React.useEffect(() => {
    if (modules && modules.length > 0 && !selectedModule) {
      // Pick a module affected by decisions like m_tests_benchmarks or fastapi
      const defaultMod = modules.find((m) => m.id === 'm_tests_benchmarks' || m.id === 'm_fastapi') || modules[0];
      setSelectedModule(defaultMod.id);
    }
  }, [modules, selectedModule]);

  // Simulate PR mutation
  const simulateMutation = useMutation({
    mutationFn: (variables: { moduleId: string; title: string }) =>
      api.simulatePR(variables.moduleId, variables.title),
    onSuccess: (data: SimulatePRResponse) => {
      queryClient.invalidateQueries({ queryKey: ['decisions'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
      queryClient.invalidateQueries({ queryKey: ['graph'] });
      setShowSimulateModal(false);

      if (data.changed && data.changed.length > 0) {
        const changesText = data.changed
          .map((c) => `${c.decision_id}: ${c.before} ➔ ${c.after}`)
          .join(', ');
        onToast?.(`PR ${data.pr_id} merged! Drift updated: ${changesText}`, 'warning');
      } else {
        onToast?.(`PR ${data.pr_id} simulated, no decisions crossed drift threshold.`, 'info');
      }
    },
    onError: (err: Error) => {
      onToast?.(`Simulation failed: ${err.message}`, 'warning');
    },
  });

  // Reset Demo mutation
  const resetMutation = useMutation({
    mutationFn: () => api.resetDemo(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['decisions'] });
      queryClient.invalidateQueries({ queryKey: ['reviews'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
      queryClient.invalidateQueries({ queryKey: ['graph'] });
      onToast?.(`Demo reset complete: ${data.removed_nodes} simulated nodes removed.`, 'success');
    },
    onError: (err: Error) => {
      onToast?.(`Reset failed: ${err.message}`, 'warning');
    },
  });

  // Refresh Ingest mutation
  const refreshMutation = useMutation({
    mutationFn: () => api.refreshIngest(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['health'] });
      queryClient.invalidateQueries({ queryKey: ['graph'] });
      onToast?.(`Ingest refreshed: ${data.new_prs} new PRs, ${data.new_files} files.`, 'success');
    },
    onError: (err: Error) => {
      onToast?.(`Refresh failed: ${err.message}`, 'warning');
    },
  });

  if (!demoMode) return null;

  return (
    <div className="flex items-center gap-2">
      {/* Simulate PR Button */}
      <button
        onClick={() => setShowSimulateModal(true)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium font-mono bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 transition-all shadow-sm"
        title="Simulate a new merged pull request to induce drift and flip decision freshness"
      >
        <Play className="w-3.5 h-3.5 text-amber-400" />
        <span>Simulate PR</span>
      </button>

      {/* Reset Demo Button */}
      <button
        onClick={() => resetMutation.mutate()}
        disabled={resetMutation.isPending}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium font-mono bg-slate-800 hover:bg-slate-750 text-slate-300 border border-slate-700/80 transition-all shadow-sm disabled:opacity-50"
        title="Reset demo PRs and all review requests back to baseline"
      >
        {resetMutation.isPending ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <RotateCcw className="w-3.5 h-3.5 text-slate-400" />
        )}
        <span>Reset</span>
      </button>

      {/* Ingest Refresh (if enabled) */}
      {ingestRefresh && (
        <button
          onClick={() => refreshMutation.mutate()}
          disabled={refreshMutation.isPending}
          className="hidden md:flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-mono text-slate-400 hover:text-slate-200 bg-slate-900 border border-slate-800 transition-all disabled:opacity-50"
          title="Refresh repository ingest from cache/GitHub"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${refreshMutation.isPending ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      )}

      {/* Simulate Change Modal Dialog */}
      {showSimulateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-md p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-amber-400" />
                <h3 className="text-sm font-semibold text-slate-100">Simulate Code Change (Demo)</h3>
              </div>
              <button
                onClick={() => setShowSimulateModal(false)}
                className="text-slate-400 hover:text-white p-1 rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              Simulates a merged pull request touching files in a specific module. This creates synthetic drift against active architecture decisions affecting that module.
            </p>

            <div className="space-y-3 font-mono text-xs">
              <div>
                <label className="block text-slate-400 mb-1.5">Target Module:</label>
                <select
                  value={selectedModule}
                  onChange={(e) => setSelectedModule(e.target.value)}
                  className="w-full bg-slate-850 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:border-amber-500"
                >
                  {modules?.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.display} ({m.path})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-slate-400 mb-1.5">PR Title:</label>
                <input
                  type="text"
                  value={prTitle}
                  onChange={(e) => setPrTitle(e.target.value)}
                  placeholder="PR Description"
                  className="w-full bg-slate-850 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:border-amber-500 font-sans"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setShowSimulateModal(false)}
                className="px-3.5 py-1.5 rounded-lg text-xs font-mono text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() =>
                  simulateMutation.mutate({
                    moduleId: selectedModule,
                    title: prTitle,
                  })
                }
                disabled={simulateMutation.isPending || !selectedModule}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium font-mono bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold transition-colors shadow-sm disabled:opacity-50"
              >
                {simulateMutation.isPending ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Check className="w-3.5 h-3.5" />
                )}
                <span>Simulate Merge</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
