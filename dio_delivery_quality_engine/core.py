from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

KST = timezone(timedelta(hours=9))

CARRIER_LABELS = {
    "epost": "우체국",
    "cj_logistics": "CJ대한통운",
}

CUTOFF_BY_CARRIER = {
    "epost": "15:00",
    "cj_logistics": "17:00",
}

ISLAND_MOUNTAIN_PATTERN = re.compile(
    r"제주|서귀포|울릉|백령|대청|소청|연평|흑산|홍도|가거도|거문도|추자|완도|진도|신안|옹진|강화|"
    r"남해군|욕지|한산|사량|돌산|금오|화정|남면|원산|삽시|외연|선유|옥도|위도"
)

@dataclass(frozen=True)
class Shipment:
    tracking_no: str
    carrier: str
    ship_date: str
    order_no: str = ""
    customer_code: str = ""
    customer_name: str = ""
    address: str = ""
    rep_name: str = ""
    dept_name: str = ""

@dataclass(frozen=True)
class TrackingRecord:
    shipment: Shipment
    api_success: bool
    api_status: str = ""
    delivered_at: str = ""
    delivered_date: str = ""
    delivered_hhmm: str = ""
    island_mountain: bool = False


def add_days(yyyy_mm_dd: str, days: int) -> str:
    return (date.fromisoformat(yyyy_mm_dd) + timedelta(days=days)).isoformat()


def normalize_date(value: Any) -> str:
    text = str(value or "").strip()
    match = re.search(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})", text)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def carrier_from_tracking_no(tracking_no: str) -> str | None:
    no = str(tracking_no or "").strip()
    if re.fullmatch(r"\d{13}", no):
        return "epost"
    if re.fullmatch(r"\d{10}|\d{12}", no):
        return "cj_logistics"
    return None


def is_friday(yyyy_mm_dd: str) -> bool:
    return date.fromisoformat(yyyy_mm_dd).weekday() == 4


def is_holiday_eve(yyyy_mm_dd: str, holidays: set[str]) -> bool:
    return add_days(yyyy_mm_dd, 1) in holidays


def exclusion_reasons(ship_date: str, holidays: set[str]) -> list[str]:
    reasons: list[str] = []
    if is_friday(ship_date):
        reasons.append("금요일 발송")
    if is_holiday_eve(ship_date, holidays):
        reasons.append("공휴일 전일 발송")
    return reasons


def is_island_mountain(address: str) -> bool:
    return bool(ISLAND_MOUNTAIN_PATTERN.search(str(address or "")))


def parse_event_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d %H%M%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=KST)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)
    except ValueError:
        return None


def kst_date(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%Y-%m-%d")


def kst_hhmm(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%H:%M")


def delivered_event_time(tracking_response: dict[str, Any]) -> datetime | None:
    history = tracking_response.get("history") or []
    delivered_events = [
        event for event in history
        if re.search(r"배송완료|배달완료", str(event.get("description", "")))
    ]
    times = [parse_event_time(event.get("time")) for event in delivered_events]
    times = [item for item in times if item is not None]
    if times:
        return max(times)
    if tracking_response.get("status") == "DELIVERED" and tracking_response.get("last_updated"):
        return parse_event_time(tracking_response.get("last_updated"))
    return None


def shipment_from_erp_row(row: dict[str, Any]) -> Shipment | None:
    tracking_no = str(row.get("sn_no") or "").strip()
    carrier = carrier_from_tracking_no(tracking_no)
    ship_date = normalize_date(row.get("out_dt"))
    if not tracking_no or not carrier or not ship_date:
        return None
    return Shipment(
        tracking_no=tracking_no,
        carrier=carrier,
        ship_date=ship_date,
        order_no=str(row.get("so_no") or "").strip(),
        customer_code=str(row.get("cust_cd") or "").strip(),
        customer_name=str(row.get("cust_nm") or row.get("n_cust_nm2") or "").strip(),
        address=str(row.get("n_addr") or "").strip(),
        rep_name=str(row.get("rep_nm") or "").strip(),
        dept_name=str(row.get("dept_nm") or "").strip(),
    )


def dedupe_shipments(rows: Iterable[dict[str, Any]]) -> list[Shipment]:
    shipments: dict[str, Shipment] = {}
    for row in rows:
        shipment = shipment_from_erp_row(row)
        if shipment and shipment.tracking_no not in shipments:
            shipments[shipment.tracking_no] = shipment
    return list(shipments.values())


def region_from_record(record: TrackingRecord) -> str:
    address = (record.shipment.address or "").strip()
    if address and address != "NA":
        parenthesized = re.match(r"^\(([^)]+)\)\s*([^\s]+)", address)
        if parenthesized:
            return f"{parenthesized.group(1)} {parenthesized.group(2)}"
        tokens = address.split()
        if len(tokens) >= 2:
            return normalize_region(f"{tokens[0]} {tokens[1]}")
        return address[:20]

    name = record.shipment.customer_name or ""
    suffix = name.split("-", 1)[1] if "-" in name else name
    parenthesized = re.match(r"\(([^)]+)\)([가-힣]+[시군구])", suffix)
    if parenthesized:
        return f"{parenthesized.group(1)} {parenthesized.group(2)}"
    simple = re.match(r"([가-힣]+(?:시|군|구))", suffix)
    if simple:
        return simple.group(1)
    return "지역미상"


def normalize_region(region: str) -> str:
    tokens = region.split()
    if len(tokens) >= 2 and tokens[-1].endswith("구") and tokens[-2].endswith("시"):
        return f"{tokens[-2]} {tokens[-1]}"
    if tokens:
        return tokens[-1]
    return "지역미상"
