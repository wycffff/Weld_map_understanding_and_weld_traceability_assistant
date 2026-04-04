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

## Current Baseline

As of the latest local run:

- `1.jpg`: drawing number is stable, weld `W01` is found, and the compact BOM now resolves to `4` usable rows instead of fragmented duplicates.
- `2.jpeg`: drawing number `C-52` is found, weld boxes are found (`W01..W11`), and the parts list now produces `6` reviewable BOM rows.
- `3.png`: line id `N-30-P-22009-AA1` is found, right-side tables now produce `3` rows, and the welding list yields `17` numeric weld IDs through review-first grid inference.
- `4.webp`: OCR can classify the page style, but text is too small for reliable title/BOM extraction; this sample remains review-first.

## Next Hardening Targets

1. Replace review-first `welding_list` row-count inference with cell-level weld-list parsing.
2. Improve `parts_list` row normalization so more `C-52` descriptions and materials survive OCR noise.
3. Add evaluation output for multi-sample regression runs.
4. Improve low-resolution fallback for stacked isometric sheets like `4.webp`.
