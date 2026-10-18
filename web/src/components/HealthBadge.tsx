import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { Database, Cpu, Activity, AlertCircle } from 'lucide-react';

interface HealthBadgeProps {
  onUnavailable?: (isUnavailable: boolean) => void;
}

export const HealthBadge: React.FC<HealthBadgeProps> = ({ onUnavailable }) => {
  const { data, isError } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.getHealth(),
    refetchInterval: 15000,
    retry: 1,
  });

  const isHealthy = data?.status === 'ok' && data.falkordb && data.mcp;
  const isDegraded = data?.status === 'degraded' || (data && (!data.falkordb || !data.mcp)) || isError;

  React.useEffect(() => {
    if (onUnavailable) {
      onUnavailable(isDegraded);
    }
  }, [isDegraded, onUnavailable]);

  if (isError) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-rose-950/60 border border-rose-800 text-rose-300 text-xs font-mono shadow-sm">
        <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping" />
        <AlertCircle className="w-3.5 h-3.5 text-rose-400" />
        <span>FalkorDB Unavailable</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900 border border-slate-800 text-slate-400 text-xs font-mono">
        <Activity className="w-3.5 h-3.5 animate-spin" />
        <span>Connecting...</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3">
      {/* Status Pill */}
      <div
        className={`flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium border shadow-sm transition-all ${
          isHealthy
            ? 'bg-emerald-950/40 border-emerald-800/80 text-emerald-300'
            : 'bg-amber-950/40 border-amber-800/80 text-amber-300'
        }`}
      >
        <span
          className={`w-2 h-2 rounded-full ${
            isHealthy ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'
          }`}
        />
        <span className="capitalize">{data.status}</span>
      </div>

      {/* Database & MCP indicators */}
      <div className="hidden sm:flex items-center gap-2 text-xs font-mono text-slate-400 bg-slate-900/80 px-2.5 py-1 rounded-md border border-slate-800">
        <div className="flex items-center gap-1.5" title="FalkorDB Graph Engine">
          <Database className={`w-3.5 h-3.5 ${data.falkordb ? 'text-emerald-400' : 'text-rose-400'}`} />
          <span className="text-slate-300">FalkorDB</span>
        </div>
        <span className="text-slate-700">|</span>
        <div className="flex items-center gap-1.5" title="MCP Server Process">
          <Cpu className={`w-3.5 h-3.5 ${data.mcp ? 'text-sky-400' : 'text-rose-400'}`} />
          <span className="text-slate-300">MCP</span>
        </div>
        {data.counts && (
          <>
            <span className="text-slate-700">|</span>
            <span className="text-slate-400">
              {data.counts.nodes.toLocaleString()} nodes · {data.counts.edges.toLocaleString()} edges
            </span>
          </>
        )}
      </div>
    </div>
  );
};
