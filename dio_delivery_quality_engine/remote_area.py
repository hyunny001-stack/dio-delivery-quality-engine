from __future__ import annotations

import csv
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AddressZipResult:
    normalized_address: str
    zipcode: str
    matched_address: str
    confidence: str
    source: str


def normalize_address(address: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", str(address or ""))
    text = re.sub(r"[,;]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_keyword(address: str) -> str:
    text = normalize_address(address)
    # Keep the address-specific part and drop floor/building tail when possible.
    text = re.sub(r"\s+\d+층.*$", "", text)
    text = re.sub(r"\s+[가-힣A-Za-z0-9]+빌딩.*$", "", text)
    return text[:80]


def lookup_juso_zip(address: str, confm_key: str | None = None, timeout: int = 10) -> AddressZipResult:
    key = confm_key or os.environ.get("JUSO_CONFM_KEY") or os.environ.get("JUSO_API_KEY")
    normalized = normalize_address(address)
    if not normalized or normalized.upper() in {"NA", "N/A", "NONE", "NULL"}:
        return AddressZipResult(normalized, "", "", "failed-empty-address", "juso")
    if not key:
        return AddressZipResult(normalized, "", "", "failed-missing-key", "juso")

    for keyword in (compact_keyword(normalized), normalized):
        params = urllib.parse.urlencode({
            "currentPage": "1",
            "countPerPage": "5",
            "keyword": keyword,
            "resultType": "json",
            "confmKey": key,
        })
        url = f"https://business.juso.go.kr/addrlink/addrLinkApi.do?{params}"
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = response.read().decode("utf-8", "ignore")
        import json
        data = json.loads(payload)
        common = data.get("results", {}).get("common", {})
        error_code = common.get("errorCode")
        if error_code not in ("0", "E0000"):
            return AddressZipResult(normalized, "", "", f"failed-{error_code}:{common.get('errorMessage')}", "juso")
        rows = data.get("results", {}).get("juso") or []
        if rows:
            top = rows[0]
            confidence = "exact" if str(common.get("totalCount")) == "1" else "candidate"
            return AddressZipResult(
                normalized_address=normalized,
                zipcode=str(top.get("zipNo") or "").strip(),
                matched_address=str(top.get("roadAddr") or top.get("jibunAddr") or "").strip(),
                confidence=confidence,
                source="juso",
            )
    return AddressZipResult(normalized, "", "", "failed-no-match", "juso")


def load_remote_ranges(csv_path: str | Path) -> list[dict[str, str]]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def match_remote_area(carrier: str, zipcode: str, ranges: list[dict[str, str]]) -> dict[str, str] | None:
    z = re.sub(r"\D", "", str(zipcode or ""))
    if not z:
        return None
    zi = int(z)
    # Prefer more specific ranges first, e.g. 제주 추자면 before 제주 전지역.
    candidates = sorted(
        [r for r in ranges if r.get("carrier") in (carrier, "all")],
        key=lambda r: int(r["zip_end"]) - int(r["zip_start"]),
    )
    for r in candidates:
        if int(r["zip_start"]) <= zi <= int(r["zip_end"]):
            return r
    return None
