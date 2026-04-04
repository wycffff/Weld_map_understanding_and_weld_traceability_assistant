from __future__ import annotations

import argparse
import json
from pathlib import Path

from weld_assistant.config import load_config
from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.services.evaluation import evaluate_structured_drawing, load_ground_truth, summarize_evaluation
from weld_assistant.services.exporter import RepositoryExporter
from weld_assistant.services.pipeline import PipelineService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Weld traceability assistant")
    parser.add_argument("--config", default="config/config.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser("parse")
    parse_cmd.add_argument("--input", required=True)
    parse_cmd.add_argument("--output")
    parse_cmd.add_argument("--persist", action="store_true")
    parse_cmd.add_argument("--overwrite", action="store_true")
    parse_cmd.add_argument("--use-vlm", action="store_true")

    parse_batch_cmd = subparsers.add_parser("parse-batch")
    parse_batch_cmd.add_argument("--input-dir", required=True)
    parse_batch_cmd.add_argument("--output", default="data/final/batch_summary.json")
    parse_batch_cmd.add_argument("--persist", action="store_true")
    parse_batch_cmd.add_argument("--overwrite", action="store_true")
    parse_batch_cmd.add_argument("--use-vlm", action="store_true")

    evaluate_cmd = subparsers.add_parser("evaluate-samples")
    evaluate_cmd.add_argument("--input-dir", default="samples/real")
    evaluate_cmd.add_argument("--ground-truth", default="eval/sample_ground_truth.json")
    evaluate_cmd.add_argument("--output", default="data/final/evaluation_report.json")
    evaluate_cmd.add_argument("--persist", action="store_true")
    evaluate_cmd.add_argument("--overwrite", action="store_true")
    evaluate_cmd.add_argument("--use-vlm", action="store_true")

    init_db_cmd = subparsers.add_parser("init-db")

    export_cmd = subparsers.add_parser("export")
    export_cmd.add_argument("--drawing-number", required=True)

    schema_cmd = subparsers.add_parser("write-schema")
    schema_cmd.add_argument("--output", default="schemas/structured_drawing.schema.json")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = load_config(args.config)
    pipeline = PipelineService(config)

    if args.command == "parse":
        structured = pipeline.process_file(
            args.input,
            persist=args.persist,
            overwrite=args.overwrite,
            use_vlm=args.use_vlm,
        )
        payload = structured.to_jsonable()
        if args.output:
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.command == "parse-batch":
        input_dir = Path(args.input_dir)
        files = [path for path in sorted(input_dir.iterdir()) if path.is_file()]
        summary: list[dict[str, object]] = []
        for path in files:
            structured = pipeline.process_file(
                path,
                persist=args.persist,
                overwrite=args.overwrite,
                use_vlm=args.use_vlm,
            )
            summary.append(
                {
                    "input_file": str(path),
                    "document_id": structured.document_id,
                    "drawing_number": structured.drawing.drawing_number,
                    "drawing_type": structured.drawing.drawing_type,
                    "supported": structured.drawing.drawing_type_supported,
                    "classification_reason": structured.drawing.classification_reason,
                    "bom_count": len(structured.bom),
                    "weld_count": len(structured.welds),
                    "review_count": len(structured.needs_review_items),
                }
            )
        Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.command == "evaluate-samples":
        input_dir = Path(args.input_dir)
        ground_truth = load_ground_truth(args.ground_truth)
        sample_reports: list[dict[str, object]] = []
        for sample_truth in ground_truth.get("samples", []):
            input_path = input_dir / Path(sample_truth["input_file"]).name
            structured = pipeline.process_file(
                input_path,
                persist=args.persist,
                overwrite=args.overwrite,
                use_vlm=args.use_vlm,
            )
            sample_reports.append(
                evaluate_structured_drawing(
                    input_file=str(input_path),
                    structured=structured,
                    sample_truth=sample_truth,
                )
            )

        payload = {
            "ground_truth_path": str(Path(args.ground_truth)),
            "aggregate": summarize_evaluation(sample_reports),
            "samples": sample_reports,
        }
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.command == "init-db":
        pipeline.repository.init_db()
        print(f"Initialized database at {config.database.path}")
        return

    if args.command == "export":
        repository = SQLiteRepository(config)
        repository.init_db()
        exporter = RepositoryExporter(config, repository)
        json_path, csv_path = exporter.export(args.drawing_number)
        print(json.dumps({"json": json_path, "csv": csv_path}, ensure_ascii=False, indent=2))
        return

    if args.command == "write-schema":
        schema_path = pipeline.write_schema(args.output)
        print(schema_path)
        return
