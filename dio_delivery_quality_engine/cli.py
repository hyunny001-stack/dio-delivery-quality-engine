from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analyzer import analyze_records
from .config import load_config, write_default_config
from .erp_source import write_erp_json
from .io import fixture_tracking_response, load_erp_json, load_tracking_cache, append_cache_record, record_from_tracking_response
from .store import db_stats, init_db, records_for_period, save_analysis_run, upsert_shipments, upsert_tracking_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DIO 국내 배송품질 분석 엔진")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-config", help="기본 분석 기준 JSON 생성")
    init.add_argument("--out", required=True)

    fetch = sub.add_parser("fetch-erp", help="ERP에서 기간별 원천 데이터 JSON 추출")
    fetch.add_argument("--start", required=True, help="YYYY-MM-DD")
    fetch.add_argument("--end", required=True, help="YYYY-MM-DD")
    fetch.add_argument("--out", required=True)
    fetch.add_argument("--endpoint", help="기본값: ERP_API_URL 환경변수")

    db_init = sub.add_parser("init-db", help="SQLite 누적 DB 초기화")
    db_init.add_argument("--db", required=True)

    ingest = sub.add_parser("ingest", help="ERP JSON과 배송조회 캐시를 SQLite DB에 누적 저장")
    ingest.add_argument("--db", required=True)
    ingest.add_argument("--erp-json", required=True)
    ingest.add_argument("--cache")

    stats = sub.add_parser("db-stats", help="SQLite DB 누적 건수 확인")
    stats.add_argument("--db", required=True)

    analyze = sub.add_parser("analyze", help="캐시/ERP 기반 배송품질 분석")
    analyze.add_argument("--erp-json", required=True)
    analyze.add_argument("--cache", required=True)
    analyze.add_argument("--out", required=True)
    analyze.add_argument("--config")
    analyze.add_argument("--track-mode", choices=["cache-only", "fixture"], default="cache-only")

    analyze_db = sub.add_parser("analyze-db", help="SQLite 누적 DB에서 기간별 배송품질 분석")
    analyze_db.add_argument("--db", required=True)
    analyze_db.add_argument("--start", required=True)
    analyze_db.add_argument("--end", required=True)
    analyze_db.add_argument("--out", required=True)
    analyze_db.add_argument("--config")
    analyze_db.add_argument("--name")
    analyze_db.add_argument("--save-run", action="store_true")
    return parser


def cmd_init_config(args: argparse.Namespace) -> None:
    write_default_config(args.out)
    print(args.out)


def cmd_fetch_erp(args: argparse.Namespace) -> None:
    write_erp_json(args.start, args.end, args.out, endpoint=args.endpoint)
    print(args.out)


def cmd_init_db(args: argparse.Namespace) -> None:
    init_db(args.db)
    print(json.dumps(db_stats(args.db), ensure_ascii=False))


def cmd_ingest(args: argparse.Namespace) -> None:
    init_db(args.db)
    shipments = load_erp_json(args.erp_json)
    shipment_count = upsert_shipments(args.db, shipments)
    tracking_count = 0
    if args.cache:
        cache = load_tracking_cache(args.cache)
        selected = [cache[s.tracking_no] for s in shipments if s.tracking_no in cache]
        tracking_count = upsert_tracking_records(args.db, selected)
    print(json.dumps({"shipmentsUpserted": shipment_count, "trackingUpserted": tracking_count, "stats": db_stats(args.db)}, ensure_ascii=False))


def cmd_db_stats(args: argparse.Namespace) -> None:
    print(json.dumps(db_stats(args.db), ensure_ascii=False))


def cmd_analyze_db(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    records = records_for_period(args.db, args.start, args.end)
    result = analyze_records(records, config)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.save_run:
        config_json = json.dumps({"configPath": args.config}, ensure_ascii=False)
        run_id = save_analysis_run(args.db, args.name, args.start, args.end, config_json, json.dumps(result, ensure_ascii=False))
        result["analysisRunId"] = run_id
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out)


def cmd_analyze(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    shipments = load_erp_json(args.erp_json)
    cache = load_tracking_cache(args.cache)

    records = []
    missing = []
    for shipment in shipments:
        cached = cache.get(shipment.tracking_no)
        if cached:
            records.append(cached)
        else:
            missing.append(shipment)

    if missing and args.track_mode == "cache-only":
        raise SystemExit(
            f"tracking cache missing {len(missing)} shipments. "
            "먼저 국내배송트레킹 조회 결과를 캐시에 저장하거나 --track-mode fixture로 구조 테스트만 실행하세요."
        )

    if args.track_mode == "fixture":
        for shipment in missing:
            record = record_from_tracking_response(shipment, fixture_tracking_response(shipment))
            append_cache_record(args.cache, record)
            records.append(record)

    result = analyze_records(records, config)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "init-config":
        cmd_init_config(args)
    elif args.command == "fetch-erp":
        cmd_fetch_erp(args)
    elif args.command == "init-db":
        cmd_init_db(args)
    elif args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "db-stats":
        cmd_db_stats(args)
    elif args.command == "analyze-db":
        cmd_analyze_db(args)
    elif args.command == "analyze":
        cmd_analyze(args)


if __name__ == "__main__":
    main()
