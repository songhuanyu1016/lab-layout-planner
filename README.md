# Lab Layout Planner

Plan optical table layouts for laser labs. Import CAD components from STEP files with actual 2D silhouette projections, arrange them on tables, and share layouts.

**[Use the Web Planner](https://songhuanyu1016.github.io/lab-layout-planner/)** — no installation needed, runs in your browser.

![Lab Layout Planner](https://img.shields.io/badge/Python-3.9%2B-blue) ![License](https://img.shields.io/badge/License-MIT-green)

## Features

- **Import STEP files** — Convert `.stp` files to component library files (`.comp.json`) with solid 2D silhouette projections from XY/XZ/YZ views
- **Component Library** — Organize components by category with a tree-view panel; double-click to place
- **Manual Components** — Add rectangular components with custom dimensions
- **Interactive Canvas** — Drag, rotate (90° snap or free), flip, lock/unlock, recolor components
- **Smart Measure** — Click two points to create persistent dimension annotations with tick marks
- **Set Distance** — Click two edges to set exact edge-to-edge spacing
- **Undo/Redo** — Full undo stack for moves, rotations, add/remove
- **Layer Order Panel** — Reorder component z-depth with drag or buttons
- **Dark/Light Theme** — Toggle between dark and light UI
- **Export PNG** — Save layout as high-resolution image
- **Rulers** — Inch/foot rulers along top and left edges
- **Persistent Settings** — Window size, grid, theme, library directory saved between sessions

## Installation

```bash
pip install PyQt5 numpy scipy cadquery
```

## Usage

### Quick Start

```bash
python lab_layout.py
```

### Convert STEP files to components

```bash
# CLI conversion (no GUI needed)
python lab_layout.py --convert input.stp output.comp.json 5.0 mm

# Or use the GUI: Edit → Convert STP to Component
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `R` / `Shift+R` | Rotate 90° CW / CCW |
| `Alt+Scroll` | Free rotate selected |
| `L` | Lock/Unlock selected |
| `M` | Measure tool |
| `Shift+Drag` | Free drag (bypass grid snap) |
| `Ctrl+Click` | Right-click (Mac trackpad) |
| `Arrow keys` | Nudge selected (grid size) |
| `Shift+Arrow` | Fine nudge (1") |
| `Ctrl+D` | Duplicate selected |
| `Ctrl+C/V` | Copy/Paste |
| `Ctrl+A` | Select all |
| `Ctrl+Z` | Undo |
| `Ctrl+Shift+Z` | Redo |
| `Ctrl+=/-` | Zoom in/out |
| `Ctrl+0` | Zoom to fit |
| `Space+Drag` | Pan |
| `Escape` | Deselect / exit tool |
| `Delete` | Remove selected |

### File Formats

- **`.comp.json`** — Component library files with 2D projections and preview images
- **`.layout.json`** — Layout files with component positions, rotations, colors, z-order
- **`.tbl.json`** — Table template files (legacy)

## Component Library

Place `.comp.json` files in the `Library/` folder next to `lab_layout.py`. They appear automatically in the Component Library panel. Right-click to organize into categories.

## Adding Components to the Shared Library

### Option 1: Upload STP file (automatic conversion)

1. Add your `.stp` file to the [`STP-upload/`](STP-upload/) folder in this repo
2. Commit and push to `main`
3. GitHub Actions automatically converts it, adds to `Library/`, and updates the web planner

### Option 2: Upload .comp.json directly

1. Convert locally: `python lab_layout.py --convert input.stp output.comp.json 5.0 mm`
2. Add the `.comp.json` file to the `Library/` folder
3. Commit and push

### Option 3: Use the web planner

1. Click **"+ Upload"** in the web planner to load a `.comp.json` file for your current session
2. To make it permanent, submit a PR adding the file to `Library/`

## License

MIT
