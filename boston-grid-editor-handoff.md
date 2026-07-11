# Boston Grid Editor — Project Handoff

## What this is

A Mario World-style schematic map editor for the Boston region, intended as the navigation layer for a hyperlocal events/transit app (the *Tonight* project). The end artifact is a stylized, tile-based map of Boston that can be used in a web interface to overlay MBTA rail lines and serve as a tap-to-navigate element.

Geographic accuracy is intentionally sacrificed in favor of readability — think the London Tube map, not a GIS layer.

---

## The file

**`boston-grid-editor.html`** — a single self-contained HTML file with no dependencies or build step. Open directly in a browser. All logic is vanilla JS + Canvas2D; the reference basemap is embedded as a base64 JPEG data URI so the file is portable.

> **Where should this file live in your project?** Drop it wherever makes sense — a `/tools` folder, `/editor`, or alongside your app's static assets. It doesn't need a server; `file://` works fine locally.

---

## Architecture

- **100 × 100 grid**, each cell 7px on a 700×700 canvas
- **Coordinate system:** `(col, row)` — col 0 = west edge, col 99 = east edge, row 0 = north, row 99 = south. North-up, harbor to the east.
- **Three data layers stacked bottom-to-top:**
  1. Reference basemap (the embedded Google Maps screenshot, drawn into the canvas)
  2. Terrain tile layer (8-bit flat-color cells, adjustable opacity)
  3. Transit line + station overlay (vector paths through cell centers, adjustable opacity)

---

## Data model

```js
// Terrain grid — 100 strings of 100 chars each
// '.' = empty (reference map shows through)
// 'g' = grass, 't' = trees, 'w' = water, 'a' = asphalt, 'h' = hills, 'd' = dirt
grid[row][col]  // char

// Transit lines
lines = [
  { name: "Red", color: "#e53935", waypoints: [[col,row], [col,row], ...] },
  ...
]

// Stations
stations = [
  { name: "Downtown", col: 53, row: 42 },
  ...
]
```

Transit line waypoints are ordered `[col, row]` pairs through cell centers. This is the coordinate format that will be used for the app's navigation layer — e.g. `(2,10) → (3,9) → (4,8) → (5,8)`.

---

## Save / load format

Clicking **Download JSON** exports:

```json
{
  "gridSize": { "cols": 100, "rows": 100 },
  "cell": 7,
  "terrain": ["....w..t...", "..."],   // one 100-char string per row
  "lines": [...],
  "stations": [...],
  "meta": { "name": "Boston schematic", "note": "col 0=W…99=E, row 0=N…99=S" }
}
```

Load via file picker, paste-and-load, or programmatically via `loadFromObj(obj)`.

---

## Editor tools

| Tool | Behavior |
|------|----------|
| Paint tile | Click or drag to fill cells with selected terrain |
| Erase | Clears cell to `.` (empty — map shows through) |
| Draw line | Pick a line, click cells in sequence to lay waypoints |
| Station | Click to drop a station marker |

Header toggles: **Map** (reference layer on/off), **Grid** (cell lines), **Labels** (schematic place names), **Build schematic** (fills terrain from a procedurally generated Boston approximation), **Clear tiles** (resets all cells to empty).

Layer opacity sliders: Map / Tiles / Lines — all independently adjustable.

---

## Current state of the terrain

The tile layer was auto-filled by sampling the reference map pixel-by-pixel:
- **Water (`w`):** any cell >50% blue pixels → 1,328 cells — harbor, Charles River, islands, Quincy Bay
- **Trees (`t`):** any cell >50% green pixels → 599 cells — parks, Emerald Necklace, suburban green
- **Everything else:** empty (`.`) — streets, buildings, etc. show through from the reference map

No transit lines or stations have been drawn yet. That's the immediate next step.

---

## Immediate next steps

1. Trace MBTA lines over the reference map using **Draw line** tool (Red, Orange, Green, Blue, Silver)
2. Drop stations at correct grid positions
3. Export the JSON coordinate model for use in the app
4. Decide on: 45°/90° waypoint snapping (more schematic look), and station-to-line linking in the data model

---

## Broader project context

This editor is a tool for building the map asset for *Tonight*, a hyperlocal events discovery app for Davis Square / Somerville / Cambridge. The app surfaces recurring "long tail" events that major aggregators miss. The transit map serves as the navigation UX — users tap a line or station to filter/browse events near that stop.

The app is live on GitHub Pages at `github.com/jpaul156/tonight`. The grid coordinate model exported from this editor will be consumed by the web app as a JSON config — no additional projection or georeferencing needed for the stylized map use case.

---

## Key design decisions already made

- **Squares over hexagons** — simpler hit-testing, cleaner web overlay
- **Schematic over geographic** — no projection math, better legibility downtown
- **Single HTML file** — no build step, no tile server, portable
- **Canvas2D + Pillow compositing model** — one image render per edit, not per-cell DOM elements
- **`(col, row)` not lat/lon** — the coordinate system is the grid itself; two anchor points (e.g. Davis Square and Logan) can be tied to real lat/lon later if needed for user-location features
