import type cytoscape from 'cytoscape';
import type { NodeLabel } from '../api/client';

export interface LabelVisualConfig {
  color: string;
  shape:
    | 'ellipse'
    | 'triangle'
    | 'rectangle'
    | 'round-rectangle'
    | 'bottom-round-rectangle'
    | 'cut-rectangle'
    | 'barrel'
    | 'rhomboid'
    | 'diamond'
    | 'pentagon'
    | 'hexagon'
    | 'concave-hexagon'
    | 'heptagon'
    | 'octagon'
    | 'star'
    | 'tag'
    | 'vee';
  displayName: string;
}

// Anti-clash Rule 4: Record<NodeLabel, LabelVisualConfig>
// A new label added to the schema will break this record and trigger a TypeScript compile error.
export const LABEL_CONFIG: Record<NodeLabel, LabelVisualConfig> = {
  Person: {
    color: '#38bdf8', // sky-400
    shape: 'ellipse',
    displayName: 'Person',
  },
  Team: {
    color: '#818cf8', // indigo-400
    shape: 'hexagon',
    displayName: 'Team',
  },
  Module: {
    color: '#34d399', // emerald-400
    shape: 'round-rectangle',
    displayName: 'Module',
  },
  File: {
    color: '#94a3b8', // slate-400
    shape: 'rectangle',
    displayName: 'File',
  },
  PR: {
    color: '#a78bfa', // violet-400
    shape: 'diamond',
    displayName: 'PR',
  },
  Doc: {
    color: '#fbbf24', // amber-400
    shape: 'tag',
    displayName: 'Doc',
  },
  Decision: {
    color: '#f43f5e', // rose-500
    shape: 'octagon',
    displayName: 'Decision',
  },
  Ticket: {
    color: '#fb923c', // orange-400
    shape: 'rhomboid',
    displayName: 'Ticket',
  },
  Thread: {
    color: '#2dd4bf', // teal-400
    shape: 'barrel',
    displayName: 'Thread',
  },
  ReviewRequest: {
    color: '#ec4899', // pink-500
    shape: 'pentagon',
    displayName: 'Review Request',
  },
};

export const cytoscapeStylesheet: cytoscape.StylesheetStyle[] = [
  // Base node styling
  {
    selector: 'node',
    style: {
      'background-color': '#64748b',
      'label': 'data(display)',
      'color': '#f8fafc',
      'font-size': '11px',
      'font-family': 'Inter, sans-serif',
      'text-valign': 'bottom',
      'text-halign': 'center',
      'text-margin-y': 4,
      'width': 28,
      'height': 28,
      'text-background-color': '#0f172a',
      'text-background-opacity': 0.85,
      'text-background-padding': '2px',
      'text-background-shape': 'roundrectangle',
      'border-width': 1.5,
      'border-color': '#334155',
      'transition-property': 'background-color, border-color, border-width, opacity, width, height',
      'transition-duration': 0.25,
    },
  },
  // Specific node colors and shapes by label
  ...(Object.entries(LABEL_CONFIG).map(([label, cfg]) => ({
    selector: `node[label = "${label}"]`,
    style: {
      'background-color': cfg.color,
      'shape': cfg.shape,
      'border-color': cfg.color,
    },
  })) as cytoscape.StylesheetStyle[]),

  // Base edge styling
  {
    selector: 'edge',
    style: {
      'width': 1.5,
      'line-color': '#334155',
      'target-arrow-color': '#334155',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      'arrow-scale': 0.8,
      'opacity': 0.65,
      'transition-property': 'line-color, target-arrow-color, width, opacity',
      'transition-duration': 0.25,
    },
  },

  // Highlighted nodes (.hl)
  {
    selector: 'node.hl',
    style: {
      'border-width': 4,
      'border-color': '#fbbf24',
      'border-opacity': 1,
      'opacity': 1.0,
      'width': 34,
      'height': 34,
      'z-index': 999,
      'text-background-color': '#78350f',
      'text-background-opacity': 0.95,
      'color': '#fef3c7',
      'font-weight': 'bold',
    },
  },

  // Highlighted edges (.hl)
  {
    selector: 'edge.hl',
    style: {
      'width': 3.5,
      'line-color': '#fbbf24',
      'target-arrow-color': '#fbbf24',
      'opacity': 1.0,
      'z-index': 998,
    },
  },

  // Selected node (user click)
  {
    selector: 'node:selected',
    style: {
      'border-width': 3.5,
      'border-color': '#38bdf8',
      'width': 34,
      'height': 34,
      'z-index': 1000,
    },
  },

  // Dimmed states when a highlight exists
  {
    selector: 'node.dimmed',
    style: {
      'opacity': 0.3,
    },
  },
  {
    selector: 'edge.dimmed',
    style: {
      'opacity': 0.15,
    },
  },
];

export const coseLayout = {
  name: 'cose',
  animate: false,
  nodeOverlap: 20,
  idealEdgeLength: 60,
  edgeElasticity: 100,
  nestingFactor: 5,
  gravity: 80,
  numIter: 1000,
  initialTemp: 200,
  coolingFactor: 0.95,
  minTemp: 1.0,
  randomize: false,
  componentSpacing: 100,
  padding: 30,
};

export const breadthfirstLayout = {
  name: 'breadthfirst',
  directed: true,
  animate: true,
  animationDuration: 500,
  spacingFactor: 1.25,
  padding: 30,
};
