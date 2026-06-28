from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import Shipment, TrackingRecord, dedupe_shipments, delivered_event_time, is_island_mountain, kst_date, kst_hhmm


def load_erp_json(path: str) -> list[Shipment]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("ERP JSON must be a list or an object with a data list")
    return dedupe_shipments(rows)


def load_tracking_cache(path: str) -> dict[str, TrackingRecord]:
    cache_path = Path(path)
    if not cache_path.exists():
        return {}
    records: dict[str, TrackingRecord] = {}
    for line in cache_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        shipment = Shipment(
            tracking_no=obj["trackingNo"],
            carrier=obj["carrier"],
            ship_date=obj["shipDate"],
            order_no=obj.get("orderNo", ""),
            customer_code=obj.get("customerCode", ""),
            customer_name=obj.get("customerName", ""),
            address=obj.get("address", ""),
            rep_name=obj.get("repName", ""),
            dept_name=obj.get("deptName", ""),
        )
        records[shipment.tracking_no] = TrackingRecord(
            shipment=shipment,
            api_success=bool(obj.get("apiSuccess")),
            api_status=str(obj.get("apiStatus", "")),
            delivered_at=str(obj.get("deliveredAt", "")),
            delivered_date=str(obj.get("deliveredDate", "")),
            delivered_hhmm=str(obj.get("deliveredHHmm", "")),
            island_mountain=bool(obj.get("island", obj.get("islandMountain", False))),
        )
    return records


def append_cache_record(path: str, record: TrackingRecord) -> None:
    obj = {
        "trackingNo": record.shipment.tracking_no,
        "carrier": record.shipment.carrier,
        "shipDate": record.shipment.ship_date,
        "orderNo": record.shipment.order_no,
        "customerCode": record.shipment.customer_code,
        "customerName": record.shipment.customer_name,
        "address": record.shipment.address,
        "repName": record.shipment.rep_name,
        "deptName": record.shipment.dept_name,
        "apiSuccess": record.api_success,
        "apiStatus": record.api_status,
        "deliveredAt": record.delivered_at,
        "deliveredDate": record.delivered_date,
        "deliveredHHmm": record.delivered_hhmm,
        "island": record.island_mountain,
    }
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def record_from_tracking_response(shipment: Shipment, response: dict[str, Any]) -> TrackingRecord:
    delivered = delivered_event_time(response) if response.get("success") else None
    return TrackingRecord(
        shipment=shipment,
        api_success=bool(response.get("success")),
        api_status=str(response.get("status") or response.get("error_code") or response.get("error") or ""),
        delivered_at=delivered.isoformat() if delivered else "",
        delivered_date=kst_date(delivered) if delivered else "",
        delivered_hhmm=kst_hhmm(delivered) if delivered else "",
        island_mountain=is_island_mountain(shipment.address),
    )


def fixture_tracking_response(shipment: Shipment) -> dict[str, Any]:
    # 테스트/구조 검증 전용. 운영 결과 산출에 사용하지 않음.
    return {
        "success": True,
        "status": "DELIVERED",
        "history": [{
            "time": f"{shipment.ship_date} 10:00:00",
            "description": "배송완료",
            "location": "fixture",
        }],
    }
