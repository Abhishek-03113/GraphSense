# GraphSense frontend

The web app for GraphSense: explore your records as a connected graph, ask questions in plain language, follow a record from start to finish, and browse everything by type.

React 19, TypeScript, Vite, React Router, TanStack Query, Zustand, Cytoscape and Zod. No CSS framework: styling is CSS Modules on top of a small set of design tokens.

## Run it

```bash
npm install
npm run dev          # http://localhost:5173
npm run lint
npm run build        # type-check + production build
npm run preview      # serve the production build
```

The app talks to the backend at `http://localhost:8000/api`. Point it elsewhere with `VITE_API_BASE_URL`:

```bash
VITE_API_BASE_URL=https://graphsense.example.com/api npm run build
```

The value is compiled into the bundle, so set it when building. For the Docker image: `docker build --build-arg VITE_API_BASE_URL=https://graphsense.example.com/api .`. The backend allows any origin by default (CORS); restrict `allow_origins` in `backend/src/main.py` for production.

## What is in the app

| Route | Page | What it does |
| --- | --- | --- |
| `/` | Overview | Dataset summary, counts per record type, relationship totals, shortcuts and flow cards. Shows a first-run "Load data" state when the dataset is empty. |
| `/explore` | Explore | The graph canvas with a floating toolbar (zoom, fit, layout), filters (record types, sample size, search), a legend, and a details panel. `?focus=<record id>` deep-links to a record. |
| `/ask` | Ask | Conversational analyst over `POST /api/chat`: suggested prompts, answer, sortable result table, query viewer, record chips that open Explore with a highlight. Also available as a side panel in Explore. |
| `/flows`, `/flows/:flowId` | Flows | Predefined business flows; a flow opens as a left-to-right graph with a legend and explanation. |
| `/trace?type=&id=` | Trace | Pick a record type and ID (with typeahead), see its lifecycle as a graph plus a step-by-step timeline. The URL is shareable. |
| `/records/:type?` | Records | Browse record types and a sample table; a row opens the same details panel. |

`Ctrl K` / `⌘K` opens the command palette from anywhere: pages, record types, flows, and record lookup by ID.

## Folder layout

```
src/
  app/            Router, providers, shell (sidebar, page frame), command palette wiring
  features/
    overview/     Overview page
    explore/      Explore page, filter panel
    ask/          Ask page, side panel, conversation, result table, prompts
    flows/        Flows list and flow detail
    trace/        Trace page and lifecycle timeline
    records/      Records browser
    inspector/    Record details panel shared by Explore, Flows, Trace and Records
    onboarding/   First-run "Load data" state
  components/
    ui/           Button, IconButton, Card, Badge, Input, Select,
                  Checkbox, Slider, Table, Sheet, Tooltip, EmptyState, Skeleton,
                  Kbd, Combobox, Disclosure, CommandPalette
    graph/        GraphCanvas (Cytoscape wrapper), toolbar, legend, layouts, theme colours
  lib/
    api/          fetch client, Zod response schemas, TanStack Query hooks
    schema/       Dataset schema: useSchema(), type and relationship metadata, colours
    format/       humanize, number/date/identifier formatting, CSV
  store/          Zustand stores: workspace (sidebar, palette, highlights) and ask (conversation)
  styles/         tokens.css (design tokens), base.css (reset and accessibility primitives)
e2e/              Mocked-API fixtures, screenshot scripts (mocked and live) and a schema drift check (not part of the bundle)
```

## The UI knows nothing about your data

No record type, relationship or property name appears in the components. Everything dataset-specific comes from `GET /api/graph/schema` through `useSchema()` in `src/lib/schema/`:

- **Labels**: `label` and `plural` for each record type, `label` for each relationship ("placed", "contains").
- **Colour**: the schema's `accent` slot (`blue`, `indigo`, ...) maps to a design token. A type without one gets a stable colour from a hash of its key, assigned so that types in one dataset do not share a colour where avoidable.
- **Primary types**: `is_primary` decides which types get overview tiles and appear first in trace pickers.
- **Details**: `display_properties` decides which properties the details panel shows first. The values come from `properties` on each graph node, and Records adds the display properties to every row of `GET /api/graph/entities/{type}`. A record with a natural name (`label` other than "<Type> <id>") is titled with it. Amounts show two decimals, with the currency of the same record when it has one. Without properties the panel says so and still lists relationships.
- **Flows**: flow definitions come with the schema; the order of `node_types` is treated as process order.

Responses are validated with Zod, and every field except `key` is optional. If the endpoint is missing (older server) or a type is not described, the app degrades instead of failing: record types come from `GET /api/graph/summary`, flows from `GET /api/graph/flows`, labels from humanising the key (`SalesOrderItem` becomes "Sales order item"), and colours from the hash. The sidebar and Overview report the dataset as "Your dataset" in that case.

The helpers on `useSchema()` are `getTypeMeta(key)`, `colorForType(key)` (a CSS variable reference), `typeLabel(key, count?)`, `edgeLabel(key, source?, target?)` and `describeEdge(key, source, target)`. `humanize()` lives in `src/lib/format/`.

## Design tokens

`src/styles/tokens.css` defines every colour, type size, spacing step, radius, control size, shadow and duration as a `--gs-*` custom property, in light and dark (`prefers-color-scheme`). Components use these properties only; nothing is hard-coded.

- Text scale for a dense desktop app: body 14/20, with caption, small, headline and title steps. System font stack, plus a monospace stack for IDs and SQL.
- One brand accent (indigo) for primary actions and selection. Everything else is neutral. The record-type palette (`--gs-hue-*`) is used for graph nodes and badges only.
- Secondary text is darker than a typical "secondary label" so that small text stays at or above 4.5:1 on every surface.
- Hit targets are 28px or larger on desktop and grow to 40px on touch and narrow screens.

Accessibility rules the code follows:

- Visible focus ring on every interactive element, full keyboard paths, skip link, focus moves to the page after navigation.
- Icon-only buttons take a required `label` prop (used as `aria-label` and tooltip).
- Status is never colour alone: the connection dot changes shape and always has text; badges carry an icon; highlighted graph records also get a heavier label.
- Every animation has a `prefers-reduced-motion` answer: CSS animations are shortened globally, graph layout and transitions are not animated.
- Records in the graph can be reached without a pointer through the Explore search results and the details panel's relationship lists.

## Visual check

`e2e/screens.mjs` builds the app against mocked API routes (fixtures in `e2e/fixtures.mjs`) and captures each page in light and dark with Playwright:

```bash
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npm run e2e:screens -- ./e2e/screens
```

It saves PNGs to the directory you pass (default `e2e/screens`, which is git-ignored) and reports any browser console errors. Set `SKIP_BUILD=1` to reuse the last build.

Two more scripts keep the mocked fixtures honest:

```bash
npm run e2e:check-schema                    # compares the SCHEMA fixture with GET /api/graph/schema of a running backend
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npm run e2e:live -- ./e2e/screens-live   # screenshots against the real backend
```

`e2e:live` expects a backend with data (see `backend/scripts/seed_demo_data.py`), builds the app against `GS_API` (default `http://localhost:8000/api`) and mocks only the chat endpoint for the populated Ask screenshot. The un-mocked Ask screenshot shows what a server without a model key says.
