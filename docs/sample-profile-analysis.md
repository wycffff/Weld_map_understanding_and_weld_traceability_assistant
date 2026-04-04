# Sample Profile Analysis

## Current Real Samples

- `samples/real/1.jpg`
  - Visual type: compact spool card with a small BOM block, one visible weld label, and a quantity/material note.
  - Human-readable anchor fields: drawing `4-N1-101`, pipe `4" SCH40`, material `ASTM A106 GR B`, weld `W-01`.
  - Parsing target: drawing info + BOM + weld label.

- `samples/real/2.jpeg`
  - Visual type: fabrication / weld-detail sheet with `W1..W11` inspection boxes, parts list, and title block.
  - Human-readable anchor fields: title block contains `C-52`, top-right `PARTS LIST`, many weld procedure boxes.
  - Parsing target: drawing number + parts list + weld box ids.

- `samples/real/3.png`
  - Visual type: welding map drawing with a centerline route, right-side erection/fabrication material tables, and a welding list.
  - Human-readable anchor fields: line id like `N-30-P-22009-AA1(3-3)`, `ERECTION MATERIALS`, `FABRICATION MATERIALS`, `WELDING LIST`.
  - Parsing target: drawing/line number + materials + weld list.

- `samples/real/4.webp`
  - Visual type: low-resolution dual isometric sheet with two stacked drawings and a large revision block.
  - Human-readable anchor fields: repeated `ISOMETRIC DRAWING`, but title/detail text is very small.
  - Parsing target: split-page layout, title block / revision block fallback, review-first workflow when OCR confidence is low.

## Current Program Strategy

- Use OCR preview tokens to classify the sheet into one of:
  - `simple_spool`
  - `fabrication_weld_sheet`
  - `welding_map_sheet`
  - `dual_isometric_sheet`
- Select ROI templates by profile instead of only by filename.
- Keep OCR as the primary source, then apply controlled heuristic normalization for:
  - drawing number cleanup
  - multiline BOM row merging
  - noisy material / quantity / part labels
- Route uncertain fields into `needs_review` instead of silently forcing a value.

## Ground Truth Snapshot

The current local ground-truth file is [eval/sample_ground_truth.json](../eval/sample_ground_truth.json).

Sample-by-sample manual truth used today:

- `1.jpg`
  - Manual truth drawing number: `4-N1-101`
  - Manual truth weld IDs: `W01`
  - Clarification: `F-9-4` is a valve/material tag, not a weld identifier.
- `2.jpeg`
  - Manual truth drawing number: `C-52`
  - Manual truth weld IDs: `W01..W11`
- `3.png`
  - Manual truth drawing number: `N-30-P-22009-AA1`
  - Manual truth weld IDs: `1..17`
  - Limitation: the current parser still reaches these via review-first welding-list inference rather than robust cell-level extraction.
- `4.webp`
  - Excluded from quantitative metrics for now.
  - Reason: the currently available source is too low-resolution to support a trustworthy human-labeled truth set.

## Current Baseline

As of the latest local run:

- `1.jpg`
  - System output drawing number: `4-N1-101`
  - System output weld IDs: `W01`
  - Status: matches the current manual truth set.
- `2.jpeg`
  - System output drawing number: `C-52`
  - System output weld IDs: `W01..W11`
  - Status: weld coverage matches the current manual truth set, but BOM quality is still review-heavy.
- `3.png`
  - System output drawing number: `N-30-P-22009-AA1`
  - System output weld IDs: `1..17`
  - Status: weld count matches the current manual truth set, but the route is still brittle because the welding list is not yet parsed at cell level.
- `4.webp`
  - System output drawing number: falls back to `document_id`
  - System output weld IDs: none
  - Status: intentional review-first / manual-intake path until a better source image is available.

## Next Hardening Targets

1. Replace review-first `welding_list` row-count inference with cell-level weld-list parsing.
2. Improve `parts_list` row normalization so more `C-52` descriptions and materials survive OCR noise.
3. Add evaluation output for multi-sample regression runs.
4. Improve low-resolution fallback for stacked isometric sheets like `4.webp`.
