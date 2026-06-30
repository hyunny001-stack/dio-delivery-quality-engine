from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections import Counter, defaultdict
from typing import Any


def parse_delivered_at(row: dict[str, Any]) -> tuple[str, str, str, str]:
    track = row.get("track") or {}
    status = str(track.get("status") or row.get("api_status") or "")
    delivered_at = ""
    if status.upper() == "DELIVERED":
        delivered_at = str(track.get("last_updated") or row.get("delivered_at") or "")
    if not delivered_at:
        for event in track.get("history") or []:
            desc = str(event.get("description") or "")
            if "배송완료" in desc:
                delivered_at = str(event.get("time") or "")
                break
    if not delivered_at:
        return status, "", "", ""
    stamp = delivered_at[:16]
    date_part = stamp[:10].replace(".", "-")
    delivered_date = date_part
    delivered_hhmm = stamp[11:16] if "T" in stamp[:11] else stamp[-5:]
    if len(delivered_hhmm) != 5 or ":" not in delivered_hhmm:
        delivered_hhmm = stamp[11:16] if len(stamp) >= 16 else ""
    return status, delivered_at, delivered_date, delivered_hhmm


def minutes_from_hhmm(hhmm: str) -> int | None:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _next_day(ship_date: str) -> str:
    return (dt.date.fromisoformat(ship_date) + dt.timedelta(days=1)).isoformat()


def _period_rows(con: sqlite3.Connection, carrier: str, start: str, end: str) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT *
        FROM carrier_switch_shipments
        WHERE carrier=? AND ship_date BETWEEN ? AND ?
        ORDER BY customer_code, ship_date, tracking_no
        """,
        (carrier, start, end),
    ).fetchall()


def _is_weekend(date_text: str) -> bool:
    return dt.date.fromisoformat(date_text).weekday() >= 5


def _metric(rows: list[sqlite3.Row]) -> dict[str, float | int]:
    analyzable = []
    for r in rows:
        if not r["delivered_date"] or not r["delivered_hhmm"]:
            continue
        if _is_weekend(r["ship_date"]) or _is_weekend(_next_day(r["ship_date"])):
            continue
        mins = minutes_from_hhmm(r["delivered_hhmm"])
        if mins is None:
            continue
        next_day = r["delivered_date"] == _next_day(r["ship_date"])
        analyzable.append({
            "next_day": next_day,
            "morning": next_day and mins < 12 * 60,
            "before15": next_day and mins < 15 * 60,
            "d2": r["delivered_date"] > _next_day(r["ship_date"]),
            "minutes": mins if next_day else None,
        })
    n = len(analyzable)
    next_rows = [x for x in analyzable if x["next_day"] and x["minutes"] is not None]
    avg = sum(float(x["minutes"] or 0) for x in next_rows) / len(next_rows) if next_rows else 0.0
    return {
        "n": n,
        "next": sum(1 for x in analyzable if x["next_day"]) / n if n else 0.0,
        "morning": sum(1 for x in analyzable if x["morning"]) / n if n else 0.0,
        "before15": sum(1 for x in analyzable if x["before15"]) / n if n else 0.0,
        "d2": sum(1 for x in analyzable if x["d2"]) / n if n else 0.0,
        "avg": avg,
    }


def analyze_carrier_switch(
    db_path: str,
    *,
    cj_start: str,
    cj_end: str,
    kp_start: str,
    kp_end: str,
    min_cj: int = 2,
    min_kp: int = 2,
    threshold_hours: float = 2.0,
) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cj_rows = _period_rows(con, "CJ", cj_start, cj_end)
    kp_rows = _period_rows(con, "KOREA_POST", kp_start, kp_end)
    by_customer: dict[str, dict[str, list[sqlite3.Row]]] = defaultdict(lambda: {"CJ": [], "KOREA_POST": []})
    names: dict[str, str] = {}
    for r in cj_rows:
        key = r["customer_code"] or r["customer_name"]
        by_customer[key]["CJ"].append(r)
        names[key] = r["customer_name"]
    for r in kp_rows:
        key = r["customer_code"] or r["customer_name"]
        by_customer[key]["KOREA_POST"].append(r)
        names[key] = r["customer_name"]

    customers = []
    summary = Counter({"KP_BETTER": 0, "CJ_BETTER": 0, "NO_CLEAR": 0, "INSUF": 0})
    for key, groups in by_customer.items():
        raw_cj = len(groups["CJ"])
        raw_kp = len(groups["KOREA_POST"])
        if raw_cj < min_cj or raw_kp < min_kp:
            continue
        cj_metric = _metric(groups["CJ"])
        kp_metric = _metric(groups["KOREA_POST"])
        fail = {"CJ_PRE": raw_cj - int(cj_metric["n"]), "KP_POST": raw_kp - int(kp_metric["n"])}
        if cj_metric["n"] < min_cj or kp_metric["n"] < min_kp:
            rec = "INSUF"
            gap = 0.0
        else:
            gap = (float(cj_metric["avg"]) - float(kp_metric["avg"])) / 60.0
            if gap >= threshold_hours:
                rec = "KP_BETTER"
            elif gap <= -threshold_hours:
                rec = "CJ_BETTER"
            else:
                rec = "NO_CLEAR"
        summary[rec] += 1
        customers.append({
            "id": key,
            "name": names.get(key, ""),
            "raw": {"pre_CJ": raw_cj, "post20_KP": raw_kp},
            "cj": cj_metric,
            "kp": kp_metric,
            "rec": rec,
            "gap": gap,
            "fail": fail,
            "attempt": {"CJ_PRE": raw_cj, "KP_POST": raw_kp},
        })
    customers.sort(key=lambda r: (r["rec"], r["id"]))
    total_shipments = con.execute("SELECT COUNT(*) FROM carrier_switch_shipments").fetchone()[0]
    candidate_shipments = sum(c["raw"]["pre_CJ"] + c["raw"]["post20_KP"] for c in customers)
    cj_to_kp = sum(c["raw"]["pre_CJ"] + c["raw"]["post20_KP"] for c in customers if c["rec"] == "KP_BETTER")
    kp_to_cj = sum(c["raw"]["pre_CJ"] + c["raw"]["post20_KP"] for c in customers if c["rec"] == "CJ_BETTER")
    return {
        "threshold": threshold_hours,
        "periods": {
            "cj_pre": f"{cj_start}~{cj_end}",
            "kp_post_trackable": f"{kp_start}~{kp_end}",
            "switch_date": "2026-05-10",
        },
        "summary": dict(summary),
        "shipments": {
            "all_20260101_20260628": total_shipments,
            "candidate_customers": len(customers),
            "candidate_shipments": candidate_shipments,
            "cj_to_kp_candidate": cj_to_kp,
            "cj_to_kp_pct_all": cj_to_kp / total_shipments * 100 if total_shipments else 0,
            "kp_to_cj_candidate": kp_to_cj,
            "kp_to_cj_pct_all": kp_to_cj / total_shipments * 100 if total_shipments else 0,
        },
        "customers": customers,
    }


def save_carrier_switch_analysis_run(db_path: str, name: str | None, params: dict[str, Any], result: dict[str, Any]) -> int:
    con = sqlite3.connect(db_path)
    with con:
        cur = con.execute(
            "INSERT INTO carrier_switch_analysis_runs(name, parameters_json, result_json) VALUES(?,?,?)",
            (name, json.dumps(params, ensure_ascii=False), json.dumps(result, ensure_ascii=False)),
        )
        return int(cur.lastrowid or 0)
