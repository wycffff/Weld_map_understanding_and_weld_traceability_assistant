from __future__ import annotations

import argparse
import json
from pathlib import Path

from weld_assistant.config import load_config
from weld_assistant.db.repository import SQLiteRepository
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
        structured = pipeline.process_file(args.input, persist=args.persist, overwrite=args.overwrite)
        payload = structured.to_jsonable()
        if args.output:
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
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

