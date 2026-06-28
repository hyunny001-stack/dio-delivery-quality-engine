from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analyzer import analyze_records
from .config import load_config, write_default_config
from .erp_source import write_erp_json
from .io import fixture_tracking_response, load_erp_json, load_tracking_cache, append_cache_record, record_from_tracking_response


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

    analyze = sub.add_parser("analyze", help="캐시/ERP 기반 배송품질 분석")
    analyze.add_argument("--erp-json", required=True)
    analyze.add_argument("--cache", required=True)
    analyze.add_argument("--out", required=True)
    analyze.add_argument("--config")
    analyze.add_argument("--track-mode", choices=["cache-only", "fixture"], default="cache-only")
    return parser


def cmd_init_config(args: argparse.Namespace) -> None:
    write_default_config(args.out)
    print(args.out)


def cmd_fetch_erp(args: argparse.Namespace) -> None:
    write_erp_json(args.start, args.end, args.out, endpoint=args.endpoint)
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
    elif args.command == "analyze":
        cmd_analyze(args)


if __name__ == "__main__":
    main()
