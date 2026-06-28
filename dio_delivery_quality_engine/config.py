from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "analysis_window_days": 40,
    "carriers": {
        "epost": {"label": "우체국", "cutoff": "15:00"},
        "cj_logistics": {"label": "CJ대한통운", "cutoff": "17:00"},
    },
    "exclude": {
        "friday_shipments": True,
        "holiday_eve_shipments": True,
        "island_mountain": True,
        "missing_delivery_time_from_quality_rate": True,
    },
    "holidays": ["2026-05-25", "2026-06-03", "2026-06-06"],
    "island_mountain_keywords": [
        "제주", "서귀포", "울릉", "백령", "대청", "소청", "연평", "흑산", "홍도", "가거도",
        "거문도", "추자", "완도", "진도", "신안", "옹진", "강화", "남해군", "욕지", "한산",
        "사량", "돌산", "금오", "화정", "남면", "원산", "삽시", "외연", "선유", "옥도", "위도",
    ],
    "quality_error_rules": {
        "non_next_day": True,
        "cutoff_fail_on_next_day": True,
    },
    "region": {
        "fallback_from_customer_name": True,
        "normalize_to_sigungu": True,
    },
}

@dataclass(frozen=True)
class CarrierRule:
    label: str
    cutoff: str

@dataclass(frozen=True)
class ExclusionRule:
    friday_shipments: bool = True
    holiday_eve_shipments: bool = True
    island_mountain: bool = True
    missing_delivery_time_from_quality_rate: bool = True

@dataclass(frozen=True)
class QualityErrorRules:
    non_next_day: bool = True
    cutoff_fail_on_next_day: bool = True

@dataclass(frozen=True)
class RegionRule:
    fallback_from_customer_name: bool = True
    normalize_to_sigungu: bool = True

@dataclass(frozen=True)
class AnalysisConfig:
    analysis_window_days: int = 40
    carriers: dict[str, CarrierRule] = field(default_factory=dict)
    exclude: ExclusionRule = field(default_factory=ExclusionRule)
    holidays: set[str] = field(default_factory=set)
    island_mountain_keywords: list[str] = field(default_factory=list)
    quality_error_rules: QualityErrorRules = field(default_factory=QualityErrorRules)
    region: RegionRule = field(default_factory=RegionRule)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def parse_config(data: dict[str, Any]) -> AnalysisConfig:
    carriers = {
        code: CarrierRule(label=str(rule["label"]), cutoff=str(rule["cutoff"]))
        for code, rule in data.get("carriers", {}).items()
    }
    return AnalysisConfig(
        analysis_window_days=int(data.get("analysis_window_days", 40)),
        carriers=carriers,
        exclude=ExclusionRule(**data.get("exclude", {})),
        holidays=set(data.get("holidays", [])),
        island_mountain_keywords=list(data.get("island_mountain_keywords", [])),
        quality_error_rules=QualityErrorRules(**data.get("quality_error_rules", {})),
        region=RegionRule(**data.get("region", {})),
    )


def load_config(path: str | None = None) -> AnalysisConfig:
    data = DEFAULT_CONFIG
    if path:
        override = json.loads(Path(path).read_text(encoding="utf-8"))
        data = deep_merge(DEFAULT_CONFIG, override)
    return parse_config(data)


def write_default_config(path: str) -> None:
    Path(path).write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
