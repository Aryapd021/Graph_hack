declare module 'react-cytoscapejs' {
  import { Component } from 'react';
  import type cytoscape from 'cytoscape';

  export interface CytoscapeComponentProps {
    id?: string;
    cy?: (cy: cytoscape.Core) => void;
    style?: React.CSSProperties;
    elements: cytoscape.ElementDefinition[];
    layout?: cytoscape.LayoutOptions;
    stylesheet?: cytoscape.StylesheetStyle[] | cytoscape.StylesheetCSS[] | any;
    className?: string;
    zoom?: number;
    pan?: { x: number; y: number };
    minZoom?: number;
    maxZoom?: number;
    zoomingEnabled?: boolean;
    userZoomingEnabled?: boolean;
    panningEnabled?: boolean;
    userPanningEnabled?: boolean;
    boxSelectionEnabled?: boolean;
    autoungrabify?: boolean;
    autounselectify?: boolean;
    wheelSensitivity?: number;
  }

  export default class CytoscapeComponent extends Component<CytoscapeComponentProps> {
    static normalizeElements(data: {
      nodes: cytoscape.NodeDefinition[];
      edges: cytoscape.EdgeDefinition[];
    }): cytoscape.ElementDefinition[];
  }
}
