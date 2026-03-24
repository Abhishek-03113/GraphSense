declare module 'react-cytoscapejs' {
  import { Component } from 'react';
  import { Core, Stylesheet, LayoutOptions } from 'cytoscape';

  interface Props {
    id?: string;
    cy?: (cy: Core) => void;
    elements: any[];
    style?: React.CSSProperties;
    stylesheet?: Stylesheet[] | string;
    layout?: LayoutOptions;
    className?: string;
    enabled?: boolean;
    concurrency?: number;
    minZoom?: number;
    maxZoom?: number;
    wheelSensitivity?: number;
  }

  export default class CytoscapeComponent extends Component<Props> {}
}
