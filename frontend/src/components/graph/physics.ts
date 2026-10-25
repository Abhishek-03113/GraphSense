import type { Core, EventObject, NodeSingular } from 'cytoscape';
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force';

interface PhysicsNode extends SimulationNodeDatum {
  id: string;
  radius: number;
  degree: number;
}

type PhysicsLink = SimulationLinkDatum<PhysicsNode>;

export interface PhysicsRun {
  /** Discard the current arrangement and spread every record out afresh. */
  scatter: boolean;
  /** Animate the simulation; when off it runs to rest in one go. */
  animate: boolean;
}

export interface Physics {
  run: (options: PhysicsRun) => void;
  destroy: () => void;
}

const FIT_PADDING = 48;
/** Ticks run before the first frame of a fresh arrangement, so the view can be fitted to a sensible shape. */
const WARMUP_TICKS = 80;
/** How hot a drag keeps the simulation: neighbours follow the dragged record while it moves. */
const DRAG_ALPHA = 0.3;
const SPAWN_JITTER = 24;
/** Shortest spring between two records. */
const LINK_BASE = 72;
/** Arc each neighbour of a hub needs on its ring: a record plus its label. */
const NEIGHBOUR_ARC = 58;
/** Room kept around a record for its label, so titles do not land on other records. */
const LABEL_CLEARANCE = 16;
/** Milliseconds between label re-placements while the graph is moving. */
const RESHAPE_EVERY_MS = 300;

/** Spring length: a hub's ring grows with its neighbour count so their labels have space. */
const linkDistance = (link: PhysicsLink) => {
  const source = link.source as PhysicsNode;
  const target = link.target as PhysicsNode;
  const ring = (Math.max(source.degree, target.degree) * NEIGHBOUR_ARC) / (2 * Math.PI);
  return Math.max(LINK_BASE, ring) + source.radius + target.radius;
};

const jitter = () => (Math.random() - 0.5) * SPAWN_JITTER;

/**
 * A live force simulation in the style of a note graph: records repel each other, relationships pull
 * like springs and a weak gravity keeps islands close. It keeps running while it settles, and dragging
 * a record reheats it so the neighbourhood follows.
 */
export function attachPhysics(cy: Core, onReshape: () => void = () => undefined): Physics {
  const known = new Map<string, PhysicsNode>();
  let elements = new Map<string, NodeSingular>();
  /** Off under reduced motion: records then stay where they are dropped instead of reheating the graph. */
  let live = true;

  const simulation: Simulation<PhysicsNode, PhysicsLink> = forceSimulation<PhysicsNode>()
    .force('charge', forceManyBody<PhysicsNode>().strength((node) => -140 - node.radius * 8).distanceMax(900))
    .force('link', forceLink<PhysicsNode, PhysicsLink>().id((node) => node.id).distance(linkDistance))
    .force('collide', forceCollide<PhysicsNode>((node) => node.radius + LABEL_CLEARANCE).strength(0.9))
    // Weak gravity: enough to keep islands on screen, not so much that unrelated clusters mesh together.
    .force('x', forceX<PhysicsNode>(0).strength(0.025))
    .force('y', forceY<PhysicsNode>(0).strength(0.025))
    .stop();

  let lastReshape = 0;
  const apply = () => {
    cy.batch(() => {
      for (const node of simulation.nodes()) {
        const element = elements.get(node.id);
        if (element && !element.grabbed()) element.position({ x: node.x ?? 0, y: node.y ?? 0 });
      }
    });
  };
  simulation.on('tick', () => {
    apply();
    // Labels wait while a record is held; the canvas places them again when it is let go.
    const now = performance.now();
    if (now - lastReshape >= RESHAPE_EVERY_MS && cy.nodes(':grabbed').empty()) {
      lastReshape = now;
      onReshape();
    }
  });
  simulation.on('end', onReshape);

  /** Build the simulation's records from the canvas, keeping the state of ones it already knows. */
  const sync = (scatter: boolean) => {
    if (scatter) known.clear();
    elements = new Map(cy.nodes().map((element) => [element.id(), element]));

    const nodes: PhysicsNode[] = [];
    const fresh: [PhysicsNode, NodeSingular][] = [];
    for (const [id, element] of elements) {
      const radius = Number(element.data('size') ?? 20) / 2;
      const degree = element.degree(false);
      const existing = known.get(id);
      if (existing) {
        existing.radius = radius;
        existing.degree = degree;
        nodes.push(existing);
        continue;
      }
      const node: PhysicsNode = { id, radius, degree };
      if (!scatter) {
        const { x, y } = element.position();
        node.x = x + jitter();
        node.y = y + jitter();
      }
      fresh.push([node, element]);
      nodes.push(node);
    }

    // A record that just appeared next to known ones starts beside them rather than at its default spot.
    for (const [node, element] of fresh) {
      const anchors = element.neighborhood('node').map((other) => known.get(other.id())).filter((other) => other !== undefined);
      if (anchors.length > 0) {
        node.x = anchors.reduce((sum, other) => sum + (other.x ?? 0), 0) / anchors.length + jitter();
        node.y = anchors.reduce((sum, other) => sum + (other.y ?? 0), 0) / anchors.length + jitter();
      }
    }

    known.clear();
    for (const node of nodes) known.set(node.id, node);

    const links: PhysicsLink[] = cy.edges().map((edge) => ({ source: edge.source().id(), target: edge.target().id() }));
    simulation.nodes(nodes);
    simulation.force<ReturnType<typeof forceLink<PhysicsNode, PhysicsLink>>>('link')?.links(links);
  };

  const run = ({ scatter, animate }: PhysicsRun) => {
    simulation.stop();
    live = animate;
    sync(scatter);
    simulation.alpha(scatter ? 1 : 0.6);

    if (!animate) {
      const ticks = Math.ceil(Math.log(simulation.alphaMin()) / Math.log(1 - simulation.alphaDecay()));
      simulation.tick(ticks);
      apply();
      onReshape();
      if (scatter) cy.fit(undefined, FIT_PADDING);
      return;
    }
    if (scatter) {
      simulation.tick(WARMUP_TICKS);
      apply();
      onReshape();
      cy.fit(undefined, FIT_PADDING);
    }
    simulation.restart();
  };

  const nodeFor = (event: EventObject) => known.get((event.target as NodeSingular).id());

  const onGrab = (event: EventObject) => {
    const node = nodeFor(event);
    if (!node || !live) return;
    const { x, y } = (event.target as NodeSingular).position();
    node.fx = x;
    node.fy = y;
    simulation.alphaTarget(DRAG_ALPHA).restart();
  };
  const onDrag = (event: EventObject) => {
    const node = nodeFor(event);
    if (!node) return;
    const { x, y } = (event.target as NodeSingular).position();
    if (!live) {
      node.x = x;
      node.y = y;
      return;
    }
    node.fx = x;
    node.fy = y;
  };
  const onFree = (event: EventObject) => {
    const node = nodeFor(event);
    if (node) {
      node.fx = null;
      node.fy = null;
    }
    if (live) simulation.alphaTarget(0);
  };

  cy.on('grab', 'node', onGrab);
  cy.on('drag', 'node', onDrag);
  cy.on('free', 'node', onFree);

  return {
    run,
    destroy: () => {
      simulation.stop();
      simulation.on('tick', null);
      cy.off('grab', 'node', onGrab);
      cy.off('drag', 'node', onDrag);
      cy.off('free', 'node', onFree);
    },
  };
}
