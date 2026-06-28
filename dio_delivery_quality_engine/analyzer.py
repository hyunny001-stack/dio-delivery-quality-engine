from __future__ import annotations

from collections import Counter
from typing import Any

from .config import AnalysisConfig
from .core import TrackingRecord, add_days, exclusion_reasons, region_from_record


def pct(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def is_excluded(record: TrackingRecord, config: AnalysisConfig) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if config.exclude.friday_shipments or config.exclude.holiday_eve_shipments:
        base_reasons = exclusion_reasons(record.shipment.ship_date, config.holidays)
        for reason in base_reasons:
            if reason == "금요일 발송" and config.exclude.friday_shipments:
                reasons.append(reason)
            if reason == "공휴일 전일 발송" and config.exclude.holiday_eve_shipments:
                reasons.append(reason)
    if config.exclude.island_mountain and record.island_mountain:
        reasons.append("도서산간")
    return bool(reasons), reasons


def is_next_day(record: TrackingRecord) -> bool:
    return bool(record.delivered_date) and record.delivered_date == add_days(record.shipment.ship_date, 1)


def is_non_next_day_error(record: TrackingRecord) -> bool:
    return bool(record.delivered_date) and not is_next_day(record)


def is_cutoff_fail(record: TrackingRecord, config: AnalysisConfig) -> bool:
    carrier_rule = config.carriers.get(record.shipment.carrier)
    if not carrier_rule or not is_next_day(record) or not record.delivered_hhmm:
        return False
    return record.delivered_hhmm > carrier_rule.cutoff


def analyze_records(records: list[TrackingRecord], config: AnalysisConfig) -> dict[str, Any]:
    excluded_counts: Counter[str] = Counter()
    included: list[TrackingRecord] = []
    for record in records:
        excluded, reasons = is_excluded(record, config)
        if excluded:
            excluded_counts["/".join(reasons)] += 1
        else:
            included.append(record)

    summary: list[dict[str, Any]] = []
    for carrier_code, carrier_rule in config.carriers.items():
        carrier_records = [r for r in included if r.shipment.carrier == carrier_code]
        delivered = [r for r in carrier_records if r.delivered_date]
        no_delivery_data = len(carrier_records) - len(delivered)
        next_day = [r for r in delivered if is_next_day(r)]
        non_next_day = [r for r in delivered if is_non_next_day_error(r)]
        cutoff_fail = [r for r in next_day if is_cutoff_fail(r, config)]

        quality_error_count = 0
        if config.quality_error_rules.non_next_day:
            quality_error_count += len(non_next_day)
        if config.quality_error_rules.cutoff_fail_on_next_day:
            quality_error_count += len(cutoff_fail)

        denominator = len(delivered) if config.exclude.missing_delivery_time_from_quality_rate else len(carrier_records)
        summary.append({
            "carrier": carrier_rule.label,
            "carrierCode": carrier_code,
            "cutoff": carrier_rule.cutoff,
            "total": len(carrier_records),
            "delivered": len(delivered),
            "nextDay": len(next_day),
            "nextDayRate": pct(len(next_day), len(delivered)),
            "nonNextDay": len(non_next_day),
            "nonNextDayRate": pct(len(non_next_day), len(delivered)),
            "cutoffFail": len(cutoff_fail),
            "cutoffFailRateOnNextDay": pct(len(cutoff_fail), len(next_day)),
            "qualityError": quality_error_count,
            "qualityErrorRate": pct(quality_error_count, denominator),
            "noDeliveryData": no_delivery_data,
        })

    non_next_day_records = [r for r in included if r.delivered_date and is_non_next_day_error(r)]
    cutoff_fail_records = [r for r in included if is_cutoff_fail(r, config)]

    return {
        "inputCount": len(records),
        "includedCount": len(included),
        "excludedCount": len(records) - len(included),
        "excludedByReason": dict(excluded_counts),
        "summary": summary,
        "regionDelay": Counter(region_from_record(r) for r in non_next_day_records).most_common(50),
        "cutoffFailRegion": Counter(region_from_record(r) for r in cutoff_fail_records).most_common(50),
        "samples": {
            "nonNextDay": [record_to_dict(r) for r in non_next_day_records[:200]],
            "cutoffFail": [record_to_dict(r) for r in cutoff_fail_records[:200]],
        },
    }


def record_to_dict(record: TrackingRecord) -> dict[str, Any]:
    return {
        "carrier": record.shipment.carrier,
        "trackingNo": record.shipment.tracking_no,
        "orderNo": record.shipment.order_no,
        "customerName": record.shipment.customer_name,
        "address": record.shipment.address,
        "shipDate": record.shipment.ship_date,
        "deliveredDate": record.delivered_date,
        "deliveredHHmm": record.delivered_hhmm,
    }
