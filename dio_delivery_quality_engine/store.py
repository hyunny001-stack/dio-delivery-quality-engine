from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .core import Shipment, TrackingRecord, is_island_mountain
from .carrier_switch import parse_delivered_at

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS shipments (
  tracking_no TEXT PRIMARY KEY,
  carrier TEXT NOT NULL,
  ship_date TEXT NOT NULL,
  order_no TEXT,
  customer_code TEXT,
  customer_name TEXT,
  address TEXT,
  rep_name TEXT,
  dept_name TEXT,
  zipcode TEXT,
  zipcode_source TEXT,
  zipcode_confidence TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_shipments_ship_date ON shipments(ship_date);
CREATE INDEX IF NOT EXISTS idx_shipments_carrier_ship_date ON shipments(carrier, ship_date);
CREATE INDEX IF NOT EXISTS idx_shipments_customer ON shipments(customer_code, customer_name);

CREATE TABLE IF NOT EXISTS tracking_results (
  tracking_no TEXT PRIMARY KEY,
  api_success INTEGER NOT NULL,
  api_status TEXT,
  delivered_at TEXT,
  delivered_date TEXT,
  delivered_hhmm TEXT,
  island_mountain INTEGER NOT NULL DEFAULT 0,
  fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(tracking_no) REFERENCES shipments(tracking_no)
);
CREATE INDEX IF NOT EXISTS idx_tracking_delivered_date ON tracking_results(delivered_date);

CREATE TABLE IF NOT EXISTS remote_area_zip_ranges (
  carrier TEXT NOT NULL,
  area_name TEXT NOT NULL,
  zip_start TEXT NOT NULL,
  zip_end TEXT NOT NULL,
  surcharge INTEGER,
  remote_type TEXT,
  source TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(carrier, area_name, zip_start, zip_end)
);
CREATE INDEX IF NOT EXISTS idx_remote_area_zip_ranges ON remote_area_zip_ranges(carrier, zip_start, zip_end);

CREATE TABLE IF NOT EXISTS address_zip_cache (
  normalized_address TEXT PRIMARY KEY,
  zipcode TEXT,
  matched_address TEXT,
  confidence TEXT,
  source TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  config_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS carrier_switch_shipments (
  tracking_no TEXT PRIMARY KEY,
  carrier TEXT NOT NULL,
  ship_date TEXT NOT NULL,
  order_no TEXT,
  customer_code TEXT,
  customer_name TEXT,
  rep_name TEXT,
  dept_name TEXT,
  api_success INTEGER NOT NULL DEFAULT 0,
  api_status TEXT,
  delivered_at TEXT,
  delivered_date TEXT,
  delivered_hhmm TEXT,
  delivery_region TEXT,
  error TEXT,
  source TEXT,
  raw_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_carrier_switch_carrier_ship_date ON carrier_switch_shipments(carrier, ship_date);
CREATE INDEX IF NOT EXISTS idx_carrier_switch_customer ON carrier_switch_shipments(customer_code, customer_name);
CREATE INDEX IF NOT EXISTS idx_carrier_switch_delivered_date ON carrier_switch_shipments(delivered_date);

CREATE TABLE IF NOT EXISTS carrier_switch_analysis_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  parameters_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

MIGRATIONS = [
    "ALTER TABLE shipments ADD COLUMN zipcode TEXT",
    "ALTER TABLE shipments ADD COLUMN zipcode_source TEXT",
    "ALTER TABLE shipments ADD COLUMN zipcode_confidence TEXT",
]


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _apply_light_migrations(con: sqlite3.Connection) -> None:
    for stmt in MIGRATIONS:
        try:
            con.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    con.execute("CREATE INDEX IF NOT EXISTS idx_shipments_zipcode ON shipments(zipcode)")


def init_db(db_path: str) -> None:
    with connect(db_path) as con:
        con.executescript(SCHEMA)
        _apply_light_migrations(con)


def upsert_shipments(db_path: str, shipments: Iterable[Shipment]) -> int:
    rows = list(shipments)
    with connect(db_path) as con:
        _apply_light_migrations(con)
        con.executemany(
            """
            INSERT INTO shipments(tracking_no, carrier, ship_date, order_no, customer_code, customer_name, address, rep_name, dept_name, zipcode, zipcode_source, zipcode_confidence)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(tracking_no) DO UPDATE SET
              carrier=excluded.carrier,
              ship_date=excluded.ship_date,
              order_no=excluded.order_no,
              customer_code=excluded.customer_code,
              customer_name=excluded.customer_name,
              address=excluded.address,
              rep_name=excluded.rep_name,
              dept_name=excluded.dept_name,
              zipcode=COALESCE(NULLIF(excluded.zipcode, ''), shipments.zipcode),
              zipcode_source=COALESCE(NULLIF(excluded.zipcode_source, ''), shipments.zipcode_source),
              zipcode_confidence=COALESCE(NULLIF(excluded.zipcode_confidence, ''), shipments.zipcode_confidence),
              updated_at=CURRENT_TIMESTAMP
            """,
            [
                (
                    s.tracking_no, s.carrier, s.ship_date, s.order_no, s.customer_code,
                    s.customer_name, s.address, s.rep_name, s.dept_name,
                    s.zipcode, s.zipcode_source, s.zipcode_confidence,
                )
                for s in rows
            ],
        )
    return len(rows)


def upsert_tracking_records(db_path: str, records: Iterable[TrackingRecord]) -> int:
    rows = list(records)
    with connect(db_path) as con:
        con.executemany(
            """
            INSERT INTO tracking_results(tracking_no, api_success, api_status, delivered_at, delivered_date, delivered_hhmm, island_mountain)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(tracking_no) DO UPDATE SET
              api_success=excluded.api_success,
              api_status=excluded.api_status,
              delivered_at=excluded.delivered_at,
              delivered_date=excluded.delivered_date,
              delivered_hhmm=excluded.delivered_hhmm,
              island_mountain=excluded.island_mountain,
              updated_at=CURRENT_TIMESTAMP
            """,
            [
                (
                    r.shipment.tracking_no, 1 if r.api_success else 0, r.api_status,
                    r.delivered_at, r.delivered_date, r.delivered_hhmm, 1 if r.island_mountain else 0,
                )
                for r in rows
            ],
        )
    return len(rows)


def seed_remote_area_ranges(db_path: str, csv_path: str) -> int:
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with connect(db_path) as con:
        con.executescript(SCHEMA)
        con.executemany(
            """
            INSERT INTO remote_area_zip_ranges(carrier, area_name, zip_start, zip_end, surcharge, remote_type, source)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(carrier, area_name, zip_start, zip_end) DO UPDATE SET
              surcharge=excluded.surcharge,
              remote_type=excluded.remote_type,
              source=excluded.source,
              updated_at=CURRENT_TIMESTAMP
            """,
            [
                (
                    r["carrier"], r["area_name"], r["zip_start"], r["zip_end"],
                    int(r["surcharge"]) if r.get("surcharge") else None,
                    r.get("remote_type", ""), r.get("source", ""),
                )
                for r in rows
            ],
        )
    return len(rows)


def remote_area_for_zip(con: sqlite3.Connection, carrier: str, zipcode: str) -> sqlite3.Row | None:
    z = ''.join(ch for ch in str(zipcode or '') if ch.isdigit())
    if not z:
        return None
    return con.execute(
        """
        SELECT *
        FROM remote_area_zip_ranges
        WHERE carrier IN (?, 'all')
          AND CAST(zip_start AS INTEGER) <= CAST(? AS INTEGER)
          AND CAST(zip_end AS INTEGER) >= CAST(? AS INTEGER)
        ORDER BY (CAST(zip_end AS INTEGER) - CAST(zip_start AS INTEGER)) ASC
        LIMIT 1
        """,
        (carrier, z, z),
    ).fetchone()


def cache_address_zip(db_path: str, normalized_address: str, zipcode: str, matched_address: str, confidence: str, source: str) -> None:
    with connect(db_path) as con:
        con.execute(
            """
            INSERT INTO address_zip_cache(normalized_address, zipcode, matched_address, confidence, source)
            VALUES(?,?,?,?,?)
            ON CONFLICT(normalized_address) DO UPDATE SET
              zipcode=excluded.zipcode,
              matched_address=excluded.matched_address,
              confidence=excluded.confidence,
              source=excluded.source,
              updated_at=CURRENT_TIMESTAMP
            """,
            (normalized_address, zipcode, matched_address, confidence, source),
        )


def apply_zipcode_to_address(db_path: str, address: str, zipcode: str, source: str, confidence: str) -> int:
    with connect(db_path) as con:
        cur = con.execute(
            """
            UPDATE shipments
            SET zipcode=?, zipcode_source=?, zipcode_confidence=?, updated_at=CURRENT_TIMESTAMP
            WHERE address=?
            """,
            (zipcode, source, confidence, address),
        )
        return int(cur.rowcount)


def upsert_carrier_switch_tracking_rows(db_path: str, rows: Iterable[dict], *, source: str = "") -> int:
    data = list(rows)
    with connect(db_path) as con:
        con.executescript(SCHEMA)
        con.executemany(
            """
            INSERT INTO carrier_switch_shipments(
              tracking_no, carrier, ship_date, order_no, customer_code, customer_name,
              rep_name, dept_name, api_success, api_status, delivered_at, delivered_date,
              delivered_hhmm, delivery_region, error, source, raw_json
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(tracking_no) DO UPDATE SET
              carrier=excluded.carrier,
              ship_date=excluded.ship_date,
              order_no=excluded.order_no,
              customer_code=excluded.customer_code,
              customer_name=excluded.customer_name,
              rep_name=excluded.rep_name,
              dept_name=excluded.dept_name,
              api_success=CASE WHEN excluded.raw_json LIKE '%"track"%' OR excluded.error <> '' THEN excluded.api_success ELSE carrier_switch_shipments.api_success END,
              api_status=CASE WHEN excluded.raw_json LIKE '%"track"%' OR excluded.error <> '' THEN excluded.api_status ELSE carrier_switch_shipments.api_status END,
              delivered_at=CASE WHEN excluded.raw_json LIKE '%"track"%' OR excluded.error <> '' THEN excluded.delivered_at ELSE carrier_switch_shipments.delivered_at END,
              delivered_date=CASE WHEN excluded.raw_json LIKE '%"track"%' OR excluded.error <> '' THEN excluded.delivered_date ELSE carrier_switch_shipments.delivered_date END,
              delivered_hhmm=CASE WHEN excluded.raw_json LIKE '%"track"%' OR excluded.error <> '' THEN excluded.delivered_hhmm ELSE carrier_switch_shipments.delivered_hhmm END,
              delivery_region=CASE WHEN excluded.raw_json LIKE '%"track"%' OR excluded.error <> '' THEN excluded.delivery_region ELSE carrier_switch_shipments.delivery_region END,
              error=CASE WHEN excluded.raw_json LIKE '%"track"%' OR excluded.error <> '' THEN excluded.error ELSE carrier_switch_shipments.error END,
              source=excluded.source,
              raw_json=CASE WHEN excluded.raw_json LIKE '%"track"%' OR excluded.error <> '' OR carrier_switch_shipments.raw_json NOT LIKE '%"track"%' THEN excluded.raw_json ELSE carrier_switch_shipments.raw_json END,
              updated_at=CURRENT_TIMESTAMP
            """,
            [_carrier_switch_tuple(row, source) for row in data],
        )
    return len(data)


def _carrier_switch_tuple(row: dict, source: str) -> tuple:
    status, delivered_at, delivered_date, delivered_hhmm = parse_delivered_at(row)
    track = row.get("track") or {}
    return (
        str(row.get("trackingNo") or row.get("tracking_no") or ""),
        str(row.get("carrier") or ""),
        str(row.get("shipDate") or row.get("ship_date") or ""),
        str(row.get("orderId") or row.get("order_no") or ""),
        str(row.get("customerId") or row.get("customer_code") or ""),
        str(row.get("customerName") or row.get("customer_name") or ""),
        str(row.get("salesRepName") or row.get("rep_name") or ""),
        str(row.get("hqName") or row.get("dept_name") or ""),
        1 if row.get("ok") else 0,
        status,
        delivered_at,
        delivered_date,
        delivered_hhmm,
        str(track.get("delivery_region") or row.get("delivery_region") or ""),
        str(row.get("error") or ""),
        source,
        json.dumps(row, ensure_ascii=False),
    )


def carrier_switch_stats(db_path: str) -> dict[str, int]:
    with connect(db_path) as con:
        con.executescript(SCHEMA)
        return {
            "carrierSwitchShipments": con.execute("SELECT COUNT(*) FROM carrier_switch_shipments").fetchone()[0],
            "carrierSwitchDelivered": con.execute("SELECT COUNT(*) FROM carrier_switch_shipments WHERE COALESCE(delivered_at,'') <> ''").fetchone()[0],
            "carrierSwitchAnalysisRuns": con.execute("SELECT COUNT(*) FROM carrier_switch_analysis_runs").fetchone()[0],
        }


def records_for_period(db_path: str, start: str, end: str, *, keyword_fallback: bool = True) -> list[TrackingRecord]:
    with connect(db_path) as con:
        _apply_light_migrations(con)
        rows = con.execute(
            """
            SELECT s.*, t.api_success, t.api_status, t.delivered_at, t.delivered_date, t.delivered_hhmm, t.island_mountain
            FROM shipments s
            LEFT JOIN tracking_results t ON t.tracking_no = s.tracking_no
            WHERE s.ship_date >= ? AND s.ship_date <= ?
            ORDER BY s.ship_date, s.tracking_no
            """,
            (start, end),
        ).fetchall()
        records: list[TrackingRecord] = []
        for row in rows:
            shipment = Shipment(
                tracking_no=row["tracking_no"],
                carrier=row["carrier"],
                ship_date=row["ship_date"],
                order_no=row["order_no"] or "",
                customer_code=row["customer_code"] or "",
                customer_name=row["customer_name"] or "",
                address=row["address"] or "",
                rep_name=row["rep_name"] or "",
                dept_name=row["dept_name"] or "",
                zipcode=row["zipcode"] or "",
                zipcode_source=row["zipcode_source"] or "",
                zipcode_confidence=row["zipcode_confidence"] or "",
            )
            remote_match = remote_area_for_zip(con, shipment.carrier, shipment.zipcode)
            remote_by_zip = remote_match is not None
            remote_by_keyword = keyword_fallback and is_island_mountain(row["address"] or "")
            records.append(TrackingRecord(
                shipment=shipment,
                api_success=bool(row["api_success"]) if row["api_success"] is not None else False,
                api_status=row["api_status"] or "",
                delivered_at=row["delivered_at"] or "",
                delivered_date=row["delivered_date"] or "",
                delivered_hhmm=row["delivered_hhmm"] or "",
                island_mountain=bool(row["island_mountain"]) or remote_by_zip or remote_by_keyword,
            ))
    return records


def save_analysis_run(db_path: str, name: str | None, start: str, end: str, config_json: str, result_json: str) -> int:
    with connect(db_path) as con:
        cur = con.execute(
            "INSERT INTO analysis_runs(name, start_date, end_date, config_json, result_json) VALUES(?,?,?,?,?)",
            (name, start, end, config_json, result_json),
        )
        return int(cur.lastrowid)


def db_stats(db_path: str) -> dict[str, int]:
    with connect(db_path) as con:
        con.executescript(SCHEMA)
        _apply_light_migrations(con)
        return {
            "shipments": con.execute("SELECT COUNT(*) FROM shipments").fetchone()[0],
            "trackingResults": con.execute("SELECT COUNT(*) FROM tracking_results").fetchone()[0],
            "remoteAreaZipRanges": con.execute("SELECT COUNT(*) FROM remote_area_zip_ranges").fetchone()[0],
            "addressZipCache": con.execute("SELECT COUNT(*) FROM address_zip_cache").fetchone()[0],
            "shipmentsWithZipcode": con.execute("SELECT COUNT(*) FROM shipments WHERE COALESCE(zipcode,'') <> ''").fetchone()[0],
            "analysisRuns": con.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0],
            "carrierSwitchShipments": con.execute("SELECT COUNT(*) FROM carrier_switch_shipments").fetchone()[0],
            "carrierSwitchDelivered": con.execute("SELECT COUNT(*) FROM carrier_switch_shipments WHERE COALESCE(delivered_at,'') <> ''").fetchone()[0],
            "carrierSwitchAnalysisRuns": con.execute("SELECT COUNT(*) FROM carrier_switch_analysis_runs").fetchone()[0],
        }
