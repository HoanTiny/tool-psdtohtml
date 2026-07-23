# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What this is

`psd2html` converts a PSD file (a Photoshop landing page design) into a working web page. Python does the
"machine" part — read the PSD accurately (layers, coordinates, text, color, export assets) — and Codex
(via the Anthropic API) does the "human" part — look at the whole design, assign semantic tags, and write
responsive CSS. Everything is Vietnamese-first: code comments, docstrings, README, and CLI help text are
written in Vietnamese (`khong dau`/ASCII-folded in places). Match that when editing this codebase — write
new comments/docstrings in Vietnamese, keep identifiers in English.

## Setup and commands

No package.json — this is a pure Python project (no Node tooling at the repo root; generated React/Next
projects have their own).

```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

There is no test suite, linter, or build step configured in this repo. `make_sample_psd.py` generates a
synthetic PSD for manual testing (needs the optional `pytoshop`/`six` deps from `requirements.txt`).

Run the pipeline from the CLI:

```powershell
# Pixel-perfect image slices, no API needed (most common mode for graphics-heavy landing pages)
venv\Scripts\python.exe -m psd2html.cli file.psd -o output --slices

# Export a React (Vite) or Next.js + Tailwind project, no API needed
venv\Scripts\python.exe -m psd2html.cli file.psd -o output --react [--lang ts] [--mobile mobile.psd]
venv\Scripts\python.exe -m psd2html.cli file.psd -o output --next

# Parse only (Phase 1), useful to inspect layout.json without calling any API
venv\Scripts\python.exe -m psd2html.cli file.psd -o output --parse-only

# Full 2-phase AI pipeline (needs ANTHROPIC_API_KEY)
$env:ANTHROPIC_API_KEY = "sk-ant-..."
venv\Scripts\python.exe -m psd2html.cli file.psd -o output

# Multiple PSDs, one per section, merged in filename order
venv\Scripts\python.exe -m psd2html.cli 01-hero.psd 02-features.psd 03-footer.psd -o output --react
```

Drag-and-drop web UI (Flask, includes a Photoshop-style per-layer editor and group-merging):

```powershell
venv\Scripts\python.exe -m psd2html.webapp
```
Opens on http://localhost:5000.

Preview a generated `output/` folder (see `.Codex/launch.json`):
```powershell
venv\Scripts\python.exe -m http.server 8123 --directory output
```

## Pipeline architecture

Two phases, connected through an on-disk `layout.json` (the sole hand-off contract between them):

```
PSD ──► Phase 1: parser.py ──► layout.json + assets/*.{webp,png} + screenshot.png
                                          │
                                          ▼
        Phase 2: (mode-dependent)  ──► HTML/CSS or React/Next project
```

**`layout.json` shape**: `{ canvas: {width, height}, screenshot, artboards: [...], layers: [...] }`.
`layers` is the *flattened* layer tree (depth-first, groups included as nodes with `kind: "group"` and a
`parent` id pointing back up). Each leaf layer has `id` (`L<n>`), `name`, `kind` (`type`/`pixel`/`shape`/
`smartobject`), `bbox` (`x/y/width/height`, already clipped to canvas), `opacity`, optional `blend` (CSS
`mix-blend-mode`), optional `text` (content/font/size/color, only for `kind: "type"`), and optional `asset`
(relative path under `assets/`). This flattened-with-parent-pointers shape is what every downstream module
(`export_web.py`, `render_slices.py`, `sectionize.py`, `fixed_overlay.py`) consumes — read `parser.py`'s
module docstring before changing the schema, since it fans out everywhere.

### Phase 1 — `parser.py`

Uses `psd_tools` to walk the layer tree and rasterize each leaf to a PNG/WebP. The tricky, load-bearing
part is *which* composite to export per layer:
- Each layer's **own composite** is used by default (already includes its layer styles — gradient, glow,
  stroke — without leaking neighboring layers' content).
- A **global composite** (`real_comp`, layer-styles included) is the fallback source when a layer's own
  composite comes back "flat"/degenerate — e.g. an adjustment layer (`_is_adjustment_kind`) or an
  unstyled shape that rendered as a solid block (`_is_flat`/`_is_uniform`). This exists to fix a specific
  class of bug where psd-tools bakes adjustment/fill layers into a flat black or white blob.
- Layers belonging to a detected **menu overlay group** (name contains "menu", height > 40% of canvas) are
  excluded from the global composite so their "ghost" doesn't bake into layers underneath (PSDs often keep
  menus open in the design).
- Every exported layer is **clipped to canvas bounds** and then **alpha-trimmed** — both because PSD layers
  routinely bleed outside the canvas, and because bleed must not leak into an adjacent section when
  multiple PSDs are merged vertically (see `merge.py`).
- Asset format defaults to WebP (lossless below `PSD2HTML_WEBP_LOSSLESS_MAX` px², lossy above), overridable
  via `.env` (`PSD2HTML_ASSET_FMT`, `PSD2HTML_WEBP_QUALITY`, `PSD2HTML_WEBP_LOSSLESS_MAX`) or CLI `--quality`.
- `scipy` is required for gradient-filled layers to render; without it those layers export blank.

### Supporting modules (all operate on `layout.json`, no AI)

- **`merge.py`** — when multiple PSD files are passed (one per section), parses each independently and
  stacks them vertically in filename order (`01-...`, `02-...`), re-offsetting bboxes and asset paths
  (`s0_*`, `s1_*`, ...) so they don't collide. Narrower sections get centered in the widest canvas.
- **`sectionize.py`** — splits a tall page into sections by finding low-content vertical bands, and
  classifies which layers are "background" per section (`is_background`, used by parser/export alike).
- **`fixed_overlay.py`** — detects layers that repeat identically across merged sections (nav/logo) by
  clustering on relative position + comparing average-hash of the asset image, then renders them once as
  `position: fixed` (slices) or a `FixedNav` component (React/Next) instead of duplicating per section.
- **`render_slices.py`** — the `--slices` mode: places every layer's exported PNG/WebP absolutely at its
  bbox, preserving stacking order and blend modes — pixel-perfect, no API call. CTA-like layers (keyword
  list `INTERACTIVE_KEYWORDS`) get wrapped in an `<a>` with hover states.
- **`export_web.py`** (~1650 lines, the largest module) — the `--react`/`--next` mode. Builds a
  Tailwind-based project with one component per section under `components/landing/`, a `Stage` component
  for responsive scaling, `Background`/`Layer` primitives, and (optionally, via `--repeats`) detects
  repeated groups (e.g. reward cards) and generates a single `.map()`-driven component instead of one
  component per instance. Also owns SEO/semantic text extraction, LCP image marking, fluid-mobile layout,
  fixed-nav/popup/nav-menu generation, and `.env`-driven config (`--env-config`).
- **`ai_enhance.py`** — optional `--ai-enhance` pass: for each generated React/Next section, asks Codex to
  "productionize" it (placeholder-looking text → real semantic `<h2>/<p>`, CTA layers → `<button>` with
  hover) while preserving pixel-perfect layout. Requires `ANTHROPIC_API_KEY`.
- **`ai_convert.py`** — Phase 2 for the AI HTML modes (`--one-shot` / `--sections`, i.e. *not*
  slices/react/next): sends the screenshot + layout to Codex and gets back full HTML/CSS. Pages taller
  than `TALL_THRESHOLD` (2500px, see `cli.py`) are automatically split into sections and converted in
  parallel (`convert_sectioned`, `max_workers`), then stitched into one `index.html`/`style.css`.
- **`webapp.py`** (~1700 lines) — Flask app behind the drag-and-drop UI. Adds a job-based workflow (upload
  → parse → optional per-layer edit/group-merge → export/preview → zip download) on top of the same
  `parser.py`/`export_web.py`/`render_slices.py` functions the CLI uses. Its own on-disk state
  (`edits.json`, `groups.json` per job) lets users merge layers into one flattened image (like a PSD
  group) or tweak per-layer properties before export, via `_apply_edits`/`_composite_members`.
- **`cli.py`** — argument parsing and orchestration only; contains no PSD/AI logic itself. `TALL_THRESHOLD`
  (auto one-shot vs. sectioned AI mode) lives here.

### Choosing a mode

| Mode | Flag | Use case | Calls AI? |
|------|------|----------|-----------|
| Slices | `--slices` | Graphics-heavy landing (game/event) — everything incl. stylized text is an image | No |
| React | `--react` | React (Vite) + Tailwind project | No |
| Next.js | `--next` | Next.js (app router) + Tailwind project | No |
| Sections | `--sections` (auto when page is tall) | Need semantic HTML with real background/foreground reconstruction | Yes |
| One-shot | `--one-shot` | Short, simple page | Yes |

When adding a feature flag that applies to React/Next, thread it through the `feats` dict passed from
`cli.py`/`webapp.py` into `export_web.export(...)` rather than adding a new positional parameter — that
dict is how `export_web.py` internals (`_gen_section`, `_gen_landing`, etc.) currently receive optional
behavior (`swiper_lib`, `popups`, `env_config`, `nav_menu`, `ai_enhance`, `fluid`).

## Known limitations (from README)

- Font/color extraction for text layers depends on PSD engine data; complex text layers may be missing it.
- Advanced blend modes, layer effects, and nested smart objects are not fully handled.
- `output*/` directories, `.psd` source files, and `venv/` are gitignored — they're regenerated, not source.
