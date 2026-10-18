import { create } from 'zustand';
import type { GraphPayload, Highlight, TraceStep } from '../api/client';

export type RightTab = 'trace' | 'decisions' | 'reviews' | 'node';

interface BrainState {
  graph: GraphPayload;
  highlight: Highlight;
  selectedNodeId: string | null;
  rightTab: RightTab;
  latestTrace: TraceStep[];

  // Actions
  setGraph: (graph: GraphPayload) => void;
  mergeGraph: (graph: GraphPayload) => void;
  setHighlight: (highlight: Highlight) => void;
  setSelectedNodeId: (id: string | null) => void;
  setRightTab: (tab: RightTab) => void;
  setLatestTrace: (trace: TraceStep[]) => void;
  resetHighlight: () => void;
}

export const useBrainStore = create<BrainState>((set) => ({
  graph: { nodes: [], edges: [] },
  highlight: { node_ids: [], edge_ids: [] },
  selectedNodeId: null,
  rightTab: 'trace',
  latestTrace: [],

  setGraph: (graph) => set({ graph }),

  mergeGraph: (newGraph) =>
    set((state) => {
      const nodeMap = new Map(state.graph.nodes.map((n) => [n.id, n]));
      for (const node of newGraph.nodes) {
        nodeMap.set(node.id, node);
      }
      const edgeMap = new Map(state.graph.edges.map((e) => [e.id, e]));
      for (const edge of newGraph.edges) {
        edgeMap.set(edge.id, edge);
      }
      return {
        graph: {
          nodes: Array.from(nodeMap.values()),
          edges: Array.from(edgeMap.values()),
        },
      };
    }),

  setHighlight: (highlight) => set({ highlight }),

  setSelectedNodeId: (id) => set({ selectedNodeId: id }),

  setRightTab: (rightTab) => set({ rightTab }),

  setLatestTrace: (latestTrace) => set({ latestTrace }),

  resetHighlight: () => set({ highlight: { node_ids: [], edge_ids: [] } }),
}));
