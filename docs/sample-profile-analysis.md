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

- `samples/real/6.jpeg`
  - Visual type: duplicate fabrication / weld-detail sheet.
  - Human-readable anchor fields: byte-identical to `samples/real/2.jpeg`.
  - Parsing target: duplicate-sample stability only; excluded from aggregate metrics.

## Current Program Strategy

- Use OCR preview tokens to classify the sheet into one of:
  - `simple_spool`
  - `fabrication_weld_map`
  - `pipeline_isometric`
  - `dual_isometric`
- Reject unsupported or unknown types early and guide the user toward manual intake.
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
  - Manual truth drawing type: `simple_spool`
  - Manual truth weld IDs: `W01`
  - Clarification: `F-9-4` is a valve/material tag, not a weld identifier.
- `2.jpeg`
  - Manual truth drawing number: `C-52`
  - Manual truth drawing type: `fabrication_weld_map`
  - Manual truth weld IDs: `W01..W11`
  - Manual truth BOM tags: `261-01`, `261-02`, `265-03`, `265-04`, `LFRDKO90520`, `NAMEPLATE-30`, `504-C1`, `504-C2`, `504-C3`, `504-C4`, `GRND`
- `3.png`
  - Manual truth drawing number: `N-30-P-22009-AA1`
  - Manual truth drawing type: `pipeline_isometric`
  - Manual truth weld IDs: `1..17`
  - Limitation: the current parser still reaches these via review-first welding-list inference rather than robust cell-level extraction.
- `4.webp`
  - Manual truth drawing type: `dual_isometric`
  - Excluded from quantitative metrics for now.
  - Reason: the currently available source is too low-resolution to support a trustworthy human-labeled truth set.
- `6.jpeg`
  - Manual truth drawing type: `fabrication_weld_map`
  - Excluded from aggregate metrics because it is a duplicate of `2.jpeg`.

## Current Baseline

As of the latest local run:

- `1.jpg`
  - System output drawing number: `4-N1-101`
  - System output drawing type: `simple_spool`
  - System output weld IDs: `W01`
  - Status: matches the current manual truth set.
- `2.jpeg`
  - System output drawing number: `C-52`
  - System output drawing type: `fabrication_weld_map`
  - System output weld IDs: `W01..W11`
  - System output BOM tags: `261-01`, `261-02`, `265-03`, `265-04`, `LFRDKO90520`, `NAMEPLATE-30`, `504-C1`, `504-C2`, `504-C3`, `504-C4`, `GRND`
  - Status: weld coverage matches the current manual truth set and the current sample evaluation reaches `bom_row_recall = 1.0` and `bom_field_accuracy = 1.0`. The rows still remain review-heavy because several values are heuristic recoveries from noisy OCR, but the normalized outputs now match the current truth set.
- `3.png`
  - System output drawing number: `N-30-P-22009-AA1`
  - System output drawing type: `pipeline_isometric`
  - System output weld IDs: `1..17`
  - Status: weld count matches the current manual truth set, but the route is still brittle because the current sample still falls back to grid-based weld-id inference when weld-list OCR is too weak for robust cell-level extraction.
- `4.webp`
  - System output drawing number: falls back to `document_id`
  - System output drawing type: `dual_isometric`
  - System output weld IDs: none
  - Status: intentional review-first / manual-intake path until a better source image is available.
- `6.jpeg`
  - System output drawing number: `C-52`
  - System output drawing type: `fabrication_weld_map`
  - Status: duplicate of `2.jpeg`; used only to verify duplicate-file handling and batch stability.

## Next Hardening Targets

1. Replace review-first `welding_list` row-count inference with cell-level weld-list parsing.
2. Improve `parts_list` row normalization so more `C-52` descriptions and materials survive OCR noise, especially beyond the currently covered 11-row truth set.
3. Add evaluation output for multi-sample regression runs.
4. Improve low-resolution fallback for stacked isometric sheets like `4.webp`.
