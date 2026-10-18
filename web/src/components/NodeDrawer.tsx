import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useBrainStore } from '../store/brainStore';
import { LABEL_CONFIG } from '../graph/style';
import { ExternalLink, Share2, Loader2, Network } from 'lucide-react';

export const NodeDrawer: React.FC = () => {
  const selectedNodeId = useBrainStore((state) => state.selectedNodeId);
  const mergeGraph = useBrainStore((state) => state.mergeGraph);

  const { data: node, isLoading, error } = useQuery({
    queryKey: ['node', selectedNodeId],
    queryFn: () => (selectedNodeId ? api.getNodeDetail(selectedNodeId) : null),
    enabled: !!selectedNodeId,
  });

  const [isExpanding, setIsExpanding] = React.useState(false);

  if (!selectedNodeId) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center text-slate-500">
        <Network className="w-10 h-10 mb-3 text-slate-600 opacity-60" />
        <p className="text-sm font-medium text-slate-400">No Node Selected</p>
        <p className="text-xs text-slate-600 mt-1 max-w-xs">
          Click any node on the graph or citation chip in chat to inspect its properties, connections, and metadata.
        </p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin text-emerald-400" />
        <span className="text-xs font-mono">Loading node details...</span>
      </div>
    );
  }

  if (error || !node) {
    return (
      <div className="p-4 text-xs text-rose-400 bg-rose-950/20 border border-rose-900 rounded-xl m-4">
        Failed to load details for node: {selectedNodeId}
      </div>
    );
  }

  const labelConfig = LABEL_CONFIG[node.label] || { color: '#64748b', displayName: node.label };

  const handleExpandNeighborhood = async () => {
    if (!selectedNodeId || isExpanding) return;
    setIsExpanding(true);
    try {
      const neighborGraph = await api.getGraphNeighborhood(selectedNodeId);
      mergeGraph(neighborGraph);
    } catch (err) {
      console.error('Failed to expand neighborhood:', err);
    } finally {
      setIsExpanding(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900/40 overflow-y-auto p-4 space-y-4">
      {/* Node Header Card */}
      <div className="p-4 rounded-xl bg-slate-850 border border-slate-800 shadow-sm space-y-2.5">
        <div className="flex items-center justify-between">
          <span
            className="px-2.5 py-1 rounded-full text-xs font-medium font-mono text-white shadow-sm"
            style={{ backgroundColor: labelConfig.color }}
          >
            {labelConfig.displayName}
          </span>

          <span className="text-xs font-mono text-slate-400">
            {node.degree} connection{node.degree === 1 ? '' : 's'}
          </span>
        </div>

        <h3 className="text-base font-semibold text-slate-100 break-words">
          {node.display}
        </h3>

        <div className="flex items-center gap-2 text-xs font-mono text-slate-400">
          <span>ID:</span>
          <span className="text-slate-300 select-all">{node.id}</span>
        </div>

        {node.url && (
          <a
            href={node.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-xs text-sky-400 hover:text-sky-300 font-mono mt-1"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            <span>Open in GitHub</span>
          </a>
        )}
      </div>

      {/* Action Buttons */}
      <div className="flex items-center gap-2">
        <button
          onClick={handleExpandNeighborhood}
          disabled={isExpanding}
          className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium transition-colors shadow-sm disabled:opacity-50"
        >
          {isExpanding ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Share2 className="w-3.5 h-3.5" />
          )}
          <span>Expand Neighborhood</span>
        </button>
      </div>

      {/* Properties Table */}
      <div className="p-3.5 rounded-xl bg-slate-850/60 border border-slate-800 space-y-2">
        <h4 className="text-xs font-mono font-semibold text-slate-400 uppercase tracking-wider">
          Properties
        </h4>
        <div className="space-y-1.5 text-xs">
          {Object.entries(node.props || {}).map(([k, v]) => {
            if (v === null || v === undefined || k === 'embedding') return null;
            return (
              <div
                key={k}
                className="flex items-start justify-between py-1 border-b border-slate-800/60 last:border-0"
              >
                <span className="font-mono text-slate-400 text-[11px] shrink-0 mr-2">{k}:</span>
                <span className="font-mono text-slate-200 text-[11px] text-right break-all">
                  {typeof v === 'boolean' ? (v ? 'true' : 'false') : String(v)}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
