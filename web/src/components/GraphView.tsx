import React, { useEffect, useRef, useState, useMemo } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import cytoscape from 'cytoscape';
import { useBrainStore } from '../store/brainStore';
import {
  cytoscapeStylesheet,
  coseLayout,
  breadthfirstLayout,
  LABEL_CONFIG,
} from '../graph/style';
import { ZoomIn, ZoomOut, Maximize2, RotateCcw, Info } from 'lucide-react';

export const GraphView: React.FC = () => {
  const cyRef = useRef<cytoscape.Core | null>(null);
  const [showLegend, setShowLegend] = useState(false);

  const graph = useBrainStore((state) => state.graph);
  const highlight = useBrainStore((state) => state.highlight);
  const selectedNodeId = useBrainStore((state) => state.selectedNodeId);
  const setSelectedNodeId = useBrainStore((state) => state.setSelectedNodeId);
  const setRightTab = useBrainStore((state) => state.setRightTab);
  const resetHighlight = useBrainStore((state) => state.resetHighlight);

  // Convert graph data into Cytoscape element definitions
  const elements = useMemo(() => {
    const cyNodes = graph.nodes.map((n) => ({
      data: {
        id: n.id,
        label: n.label,
        display: n.display,
        ...n.props,
      },
    }));

    const cyEdges = graph.edges.map((e) => ({
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        type: e.type,
      },
    }));

    return CytoscapeComponent.normalizeElements({
      nodes: cyNodes,
      edges: cyEdges,
    });
  }, [graph]);

  // Determine layout: breadthfirst if highlight exists (trace path), else cose
  const layout = useMemo(() => {
    if (highlight.node_ids.length > 0 && highlight.node_ids.length <= 15) {
      return breadthfirstLayout;
    }
    return coseLayout;
  }, [highlight.node_ids.length]);

  // Update Cytoscape classes when highlight or selectedNodeId changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.batch(() => {
      const hasHighlight = highlight.node_ids.length > 0 || highlight.edge_ids.length > 0;
      const hlNodeSet = new Set(highlight.node_ids);
      const hlEdgeSet = new Set(highlight.edge_ids);

      cy.nodes().forEach((node) => {
        const id = node.id();
        if (hasHighlight) {
          if (hlNodeSet.has(id)) {
            node.addClass('hl');
            node.removeClass('dimmed');
          } else {
            node.removeClass('hl');
            node.addClass('dimmed');
          }
        } else {
          node.removeClass('hl');
          node.removeClass('dimmed');
        }

        // Selection
        if (selectedNodeId && id === selectedNodeId) {
          node.select();
        } else {
          node.unselect();
        }
      });

      cy.edges().forEach((edge) => {
        const id = edge.id();
        if (hasHighlight) {
          if (hlEdgeSet.has(id)) {
            edge.addClass('hl');
            edge.removeClass('dimmed');
          } else {
            edge.removeClass('hl');
            edge.addClass('dimmed');
          }
        } else {
          edge.removeClass('hl');
          edge.removeClass('dimmed');
        }
      });
    });

    // If highlight changed, animate zoom fit to the highlighted nodes
    if (highlight.node_ids.length > 0) {
      const hlCollection = cy.nodes().filter((n) => highlight.node_ids.includes(n.id()));
      if (hlCollection.length > 0) {
        cy.animate(
          {
            fit: {
              eles: hlCollection,
              padding: 60,
            },
          },
          { duration: 600 }
        );
      }
    }
  }, [highlight, selectedNodeId]);

  // Initialize event handlers
  const handleCy = (cy: cytoscape.Core) => {
    cyRef.current = cy;

    cy.on('tap', 'node', (evt) => {
      const node = evt.target;
      const nodeId = node.id();
      setSelectedNodeId(nodeId);
      setRightTab('node');
    });

    cy.on('tap', (evt) => {
      if (evt.target === cy) {
        setSelectedNodeId(null);
      }
    });
  };

  const handleFit = () => {
    if (cyRef.current) {
      cyRef.current.animate({ fit: { eles: cyRef.current.elements(), padding: 40 } }, { duration: 400 });
    }
  };

  const handleZoomIn = () => {
    if (cyRef.current) {
      cyRef.current.zoom(cyRef.current.zoom() * 1.3);
    }
  };

  const handleZoomOut = () => {
    if (cyRef.current) {
      cyRef.current.zoom(cyRef.current.zoom() / 1.3);
    }
  };

  return (
    <div className="relative w-full h-full bg-slate-950 overflow-hidden">
      {/* Cytoscape Canvas */}
      <CytoscapeComponent
        elements={elements}
        stylesheet={cytoscapeStylesheet}
        layout={layout}
        className="w-full h-full"
        cy={handleCy}
        minZoom={0.2}
        maxZoom={3.0}
        wheelSensitivity={0.2}
      />

      {/* Floating Controls Bar */}
      <div className="absolute top-4 right-4 flex items-center gap-1.5 p-1 bg-slate-900/90 backdrop-blur-md border border-slate-800 rounded-xl shadow-lg z-10">
        <button
          onClick={handleZoomIn}
          className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-850 transition-colors"
          title="Zoom In"
        >
          <ZoomIn className="w-4 h-4" />
        </button>
        <button
          onClick={handleZoomOut}
          className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-850 transition-colors"
          title="Zoom Out"
        >
          <ZoomOut className="w-4 h-4" />
        </button>
        <button
          onClick={handleFit}
          className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-850 transition-colors"
          title="Fit Graph"
        >
          <Maximize2 className="w-4 h-4" />
        </button>

        {highlight.node_ids.length > 0 && (
          <button
            onClick={resetHighlight}
            className="p-1.5 rounded-lg text-amber-400 hover:text-amber-300 hover:bg-slate-850 transition-colors border-l border-slate-800"
            title="Reset Highlight"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        )}

        <button
          onClick={() => setShowLegend(!showLegend)}
          className={`p-1.5 rounded-lg transition-colors border-l border-slate-800 ${
            showLegend ? 'text-emerald-400 bg-slate-850' : 'text-slate-400 hover:text-white'
          }`}
          title="Toggle Legend"
        >
          <Info className="w-4 h-4" />
        </button>
      </div>

      {/* Legend Modal / Drawer */}
      {showLegend && (
        <div className="absolute bottom-4 right-4 p-3.5 bg-slate-900/95 backdrop-blur-md border border-slate-800 rounded-xl shadow-2xl z-10 w-64 max-h-96 overflow-y-auto">
          <h4 className="text-xs font-semibold text-slate-300 mb-2 uppercase tracking-wider font-mono">
            Graph Node Legend
          </h4>
          <div className="space-y-1.5 text-xs">
            {Object.entries(LABEL_CONFIG).map(([label, cfg]) => (
              <div key={label} className="flex items-center gap-2 text-slate-300">
                <span
                  className="w-3.5 h-3.5 rounded shrink-0 border border-slate-700/80"
                  style={{ backgroundColor: cfg.color }}
                />
                <span className="font-mono text-[11px] text-slate-200">{label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Subgraph Info Badge */}
      <div className="absolute bottom-4 left-4 px-3 py-1.5 bg-slate-900/80 backdrop-blur-md border border-slate-800 rounded-lg text-xs font-mono text-slate-400 z-10 pointer-events-none">
        <span>{graph.nodes.length} rendered nodes · {graph.edges.length} edges</span>
        {highlight.node_ids.length > 0 && (
          <span className="text-amber-400 ml-2 font-medium">
            ({highlight.node_ids.length} highlighted)
          </span>
        )}
      </div>
    </div>
  );
};
