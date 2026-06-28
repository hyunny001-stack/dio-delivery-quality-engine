from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .core import Shipment, TrackingRecord

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

CREATE TABLE IF NOT EXISTS analysis_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  config_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def init_db(db_path: str) -> None:
    with connect(db_path) as con:
        con.executescript(SCHEMA)


def upsert_shipments(db_path: str, shipments: Iterable[Shipment]) -> int:
    rows = list(shipments)
    with connect(db_path) as con:
        con.executemany(
            """
            INSERT INTO shipments(tracking_no, carrier, ship_date, order_no, customer_code, customer_name, address, rep_name, dept_name)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(tracking_no) DO UPDATE SET
              carrier=excluded.carrier,
              ship_date=excluded.ship_date,
              order_no=excluded.order_no,
              customer_code=excluded.customer_code,
              customer_name=excluded.customer_name,
              address=excluded.address,
              rep_name=excluded.rep_name,
              dept_name=excluded.dept_name,
              updated_at=CURRENT_TIMESTAMP
            """,
            [
                (
                    s.tracking_no, s.carrier, s.ship_date, s.order_no, s.customer_code,
                    s.customer_name, s.address, s.rep_name, s.dept_name,
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


def records_for_period(db_path: str, start: str, end: str) -> list[TrackingRecord]:
    with connect(db_path) as con:
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
        )
        records.append(TrackingRecord(
            shipment=shipment,
            api_success=bool(row["api_success"]) if row["api_success"] is not None else False,
            api_status=row["api_status"] or "",
            delivered_at=row["delivered_at"] or "",
            delivered_date=row["delivered_date"] or "",
            delivered_hhmm=row["delivered_hhmm"] or "",
            island_mountain=bool(row["island_mountain"]),
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
        return {
            "shipments": con.execute("SELECT COUNT(*) FROM shipments").fetchone()[0],
            "trackingResults": con.execute("SELECT COUNT(*) FROM tracking_results").fetchone()[0],
            "analysisRuns": con.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0],
        }
