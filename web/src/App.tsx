import React, { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, type GraphPayload } from './api/client';
import { useBrainStore } from './store/brainStore';
import { HealthBadge } from './components/HealthBadge';
import { ChatPanel } from './components/ChatPanel';
import { GraphView } from './components/GraphView';
import { TracePanel } from './components/TracePanel';
import { NodeDrawer } from './components/NodeDrawer';
import { DecisionsBoard } from './components/DecisionsBoard';
import { ReviewsPanel } from './components/ReviewsPanel';
import { DemoControls } from './components/DemoControls';
import {
  Brain,
  Terminal,
  Network,
  FileText,
  CheckSquare,
  AlertOctagon,
  RefreshCw,
  Info,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';

interface Toast {
  id: string;
  message: string;
  type: 'success' | 'info' | 'warning';
}

export const App: React.FC = () => {
  const setGraph = useBrainStore((state) => state.setGraph);
  const rightTab = useBrainStore((state) => state.rightTab);
  const setRightTab = useBrainStore((state) => state.setRightTab);
  const selectedNodeId = useBrainStore((state) => state.selectedNodeId);

  const [isGraphUnavailable, setIsGraphUnavailable] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = (message: string, type: 'success' | 'info' | 'warning' = 'info') => {
    const id = `toast-${Date.now()}-${Math.random()}`;
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  };

  // Initial load: Fetch health for demo mode flags
  const { data: healthData } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.getHealth(),
  });

  // Initial load: Fetch graph overview (150 nodes/edges per Section 15)
  const { data: initialOverview, refetch: refetchOverview } = useQuery<GraphPayload>({
    queryKey: ['graph', 'overview'],
    queryFn: () => api.getGraphOverview(150),
    staleTime: Infinity,
    retry: 2,
  });

  useEffect(() => {
    if (initialOverview) {
      setGraph(initialOverview);
    }
  }, [initialOverview, setGraph]);

  return (
    <div className="flex flex-col h-screen w-screen bg-slate-950 text-slate-100 overflow-hidden font-sans">
      {/* 503 Persistent Degradation Banner per Section 14 & 15 */}
      {isGraphUnavailable && (
        <div className="bg-rose-950 border-b border-rose-800 px-4 py-2 flex items-center justify-between text-xs text-rose-200 z-50 animate-pulse">
          <div className="flex items-center gap-2">
            <AlertOctagon className="w-4 h-4 text-rose-400 shrink-0" />
            <span className="font-medium">
              FalkorDB Graph Engine is unavailable (503 GRAPH_UNAVAILABLE). The knowledge graph is offline.
            </span>
          </div>
          <button
            onClick={() => refetchOverview()}
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-rose-900 hover:bg-rose-850 text-rose-200 font-mono transition-colors"
          >
            <RefreshCw className="w-3 h-3" />
            <span>Retry</span>
          </button>
        </div>
      )}

      {/* Top Application Bar */}
      <header className="h-14 border-b border-slate-800 bg-slate-900/90 backdrop-blur-md px-4 flex items-center justify-between shrink-0 z-20">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-500 p-0.5 shadow-md flex items-center justify-center">
            <Brain className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-bold tracking-tight text-white">Company Brain</h1>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-emerald-950 border border-emerald-800/80 text-emerald-400">
                Track 03
              </span>
            </div>
            <p className="text-[11px] text-slate-400 leading-tight">
              Graph-Backed Organizational Intelligence · FalkorDB + MCP
            </p>
          </div>
        </div>

        {/* Demo Controls & Health status badge */}
        <div className="flex items-center gap-3">
          <DemoControls
            demoMode={healthData?.demo_mode ?? true}
            ingestRefresh={healthData?.ingest_refresh ?? true}
            onToast={addToast}
          />
          <div className="h-5 w-px bg-slate-800 hidden sm:block" />
          <HealthBadge onUnavailable={setIsGraphUnavailable} />
        </div>
      </header>

      {/* Main Three-Column Workspace */}
      <main className="flex-1 flex overflow-hidden">
        {/* Column 1: Chat Assistant (380px) */}
        <section className="w-96 shrink-0 h-full flex flex-col">
          <ChatPanel />
        </section>

        {/* Column 2: Interactive Graph View (Center, flex-1) */}
        <section className="flex-1 h-full relative border-r border-slate-800">
          <GraphView />
        </section>

        {/* Column 3: Right Inspector Tabs (380px) */}
        <section className="w-96 shrink-0 h-full flex flex-col bg-slate-900/50">
          {/* Tab Navigation Headers */}
          <div className="flex items-center border-b border-slate-800 bg-slate-900/80 px-2 pt-2">
            <button
              onClick={() => setRightTab('trace')}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-mono font-medium border-b-2 transition-all ${
                rightTab === 'trace'
                  ? 'border-emerald-500 text-emerald-400 bg-slate-850/60 rounded-t-lg'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Terminal className="w-3.5 h-3.5" />
              <span>Trace</span>
            </button>

            <button
              onClick={() => setRightTab('decisions')}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-mono font-medium border-b-2 transition-all ${
                rightTab === 'decisions'
                  ? 'border-emerald-500 text-emerald-400 bg-slate-850/60 rounded-t-lg'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>Decisions</span>
            </button>

            <button
              onClick={() => setRightTab('reviews')}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-mono font-medium border-b-2 transition-all ${
                rightTab === 'reviews'
                  ? 'border-emerald-500 text-emerald-400 bg-slate-850/60 rounded-t-lg'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <CheckSquare className="w-3.5 h-3.5" />
              <span>Reviews</span>
            </button>

            <button
              onClick={() => setRightTab('node')}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-mono font-medium border-b-2 transition-all ${
                rightTab === 'node'
                  ? 'border-emerald-500 text-emerald-400 bg-slate-850/60 rounded-t-lg'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Network className="w-3.5 h-3.5" />
              <span>Node</span>
              {selectedNodeId && (
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse ml-0.5" />
              )}
            </button>
          </div>

          {/* Active Tab Content */}
          <div className="flex-1 overflow-hidden">
            {rightTab === 'trace' && <TracePanel />}
            {rightTab === 'decisions' && <DecisionsBoard onToast={addToast} />}
            {rightTab === 'reviews' && <ReviewsPanel />}
            {rightTab === 'node' && <NodeDrawer />}
          </div>
        </section>
      </main>

      {/* Toast Notification Container */}
      {toasts.length > 0 && (
        <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 max-w-sm pointer-events-none">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={`pointer-events-auto px-4 py-3 rounded-xl shadow-2xl border text-xs leading-relaxed flex items-center gap-2.5 backdrop-blur-md animate-fade-in ${
                toast.type === 'success'
                  ? 'bg-emerald-950/90 border-emerald-700/80 text-emerald-200'
                  : toast.type === 'warning'
                  ? 'bg-amber-950/90 border-amber-700/80 text-amber-200'
                  : 'bg-slate-900/90 border-slate-700/80 text-slate-200'
              }`}
            >
              {toast.type === 'success' && <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />}
              {toast.type === 'warning' && <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />}
              {toast.type === 'info' && <Info className="w-4 h-4 text-sky-400 shrink-0" />}
              <span>{toast.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
export default App;
