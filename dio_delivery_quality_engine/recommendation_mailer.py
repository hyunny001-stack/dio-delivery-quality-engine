from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Any

MAILER_SCHEMA = """
CREATE TABLE IF NOT EXISTS monthly_carrier_recommendations (
  month TEXT NOT NULL,
  customer_code TEXT NOT NULL,
  customer_name TEXT NOT NULL,
  branch_name TEXT,
  sales_rep_name TEXT,
  current_main_carrier TEXT,
  recommended_carrier TEXT NOT NULL,
  grade TEXT NOT NULL,
  reason TEXT,
  cj_recent_n INTEGER DEFAULT 0,
  kp_recent_n INTEGER DEFAULT 0,
  cj_next_rate REAL,
  kp_next_rate REAL,
  cj_avg_arrival TEXT,
  kp_avg_arrival TEXT,
  raw_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(month, customer_code, recommended_carrier)
);

CREATE TABLE IF NOT EXISTS sales_rep_email_map (
  sales_rep_name TEXT NOT NULL,
  branch_name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(sales_rep_name, branch_name)
);

CREATE TABLE IF NOT EXISTS recommendation_email_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  month TEXT NOT NULL,
  recipient_email TEXT NOT NULL,
  sales_rep_name TEXT,
  branch_name TEXT,
  recommendation_count INTEGER NOT NULL,
  subject TEXT NOT NULL,
  body_preview TEXT,
  body TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  sent_at TEXT
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(MAILER_SCHEMA)
    return con


def seed_sales_rep_emails(db_path: str, rows: Iterable[dict[str, Any]]) -> int:
    data = list(rows)
    with _connect(db_path) as con:
        con.executemany(
            """
            INSERT INTO sales_rep_email_map(sales_rep_name, branch_name, email, active)
            VALUES(?,?,?,?)
            ON CONFLICT(sales_rep_name, branch_name) DO UPDATE SET
              email=excluded.email,
              active=excluded.active,
              updated_at=CURRENT_TIMESTAMP
            """,
            [(
                str(r.get("sales_rep_name") or r.get("rep") or "").strip(),
                str(r.get("branch_name") or r.get("branch") or "").strip(),
                str(r.get("email") or "").strip(),
                1 if str(r.get("active", "1")).strip().lower() not in {"0", "false", "n", "no"} else 0,
            ) for r in data if str(r.get("email") or "").strip()],
        )
    return len(data)


def load_sales_rep_email_csv(path: str) -> list[dict[str, Any]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def upsert_monthly_recommendations(db_path: str, month: str, recommendations: Iterable[dict[str, Any]]) -> int:
    data = list(recommendations)
    with _connect(db_path) as con:
        con.executemany(
            """
            INSERT INTO monthly_carrier_recommendations(
              month, customer_code, customer_name, branch_name, sales_rep_name,
              current_main_carrier, recommended_carrier, grade, reason,
              cj_recent_n, kp_recent_n, cj_next_rate, kp_next_rate,
              cj_avg_arrival, kp_avg_arrival, raw_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(month, customer_code, recommended_carrier) DO UPDATE SET
              customer_name=excluded.customer_name,
              branch_name=excluded.branch_name,
              sales_rep_name=excluded.sales_rep_name,
              current_main_carrier=excluded.current_main_carrier,
              grade=excluded.grade,
              reason=excluded.reason,
              cj_recent_n=excluded.cj_recent_n,
              kp_recent_n=excluded.kp_recent_n,
              cj_next_rate=excluded.cj_next_rate,
              kp_next_rate=excluded.kp_next_rate,
              cj_avg_arrival=excluded.cj_avg_arrival,
              kp_avg_arrival=excluded.kp_avg_arrival,
              raw_json=excluded.raw_json,
              updated_at=CURRENT_TIMESTAMP
            """,
            [
                (
                    month,
                    str(r.get("customer_code") or r.get("code") or "").strip(),
                    str(r.get("customer_name") or r.get("name") or "").strip(),
                    str(r.get("branch_name") or "").strip(),
                    str(r.get("sales_rep_name") or "").strip(),
                    str(r.get("current_main_carrier") or "").strip(),
                    str(r.get("recommended_carrier") or "CJ").strip(),
                    _normalize_grade(str(r.get("grade") or "").strip()),
                    str(r.get("reason") or "").strip(),
                    int(r.get("cj_recent_n") or 0),
                    int(r.get("kp_recent_n") or 0),
                    _float_or_none(r.get("cj_next_rate")),
                    _float_or_none(r.get("kp_next_rate")),
                    str(r.get("cj_avg_arrival") or "").strip(),
                    str(r.get("kp_avg_arrival") or "").strip(),
                    json.dumps(r, ensure_ascii=False),
                ) for r in data
            ],
        )
    return len(data)


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _normalize_grade(grade: str) -> str:
    if grade.startswith("A"):
        return "A"
    if grade.startswith("B"):
        return "B"
    if grade.startswith("C"):
        return "C"
    if grade.startswith("D"):
        return "D"
    return grade or "B"


def recommendations_from_recent_rejudgement(db_path: str, month: str, rejudgement_json_path: str, *, allowed_grades: tuple[str, ...] = ("A", "B")) -> list[dict[str, Any]]:
    data = json.loads(Path(rejudgement_json_path).read_text(encoding="utf-8"))
    candidates = data.get("previous_candidates") or []
    recommendations: list[dict[str, Any]] = []
    for r in candidates:
        grade = _normalize_grade(str(r.get("grade") or ""))
        if grade not in allowed_grades:
            continue
        code = str(r.get("code") or "").strip()
        branch, rep = latest_branch_rep_for_customer(db_path, code)
        recommendations.append({
            "customer_code": code,
            "customer_name": r.get("name") or "",
            "branch_name": branch,
            "sales_rep_name": rep,
            "current_main_carrier": "KOREA_POST",
            "recommended_carrier": "CJ",
            "grade": grade,
            "reason": r.get("reason") or r.get("action") or "CJ 예외 발송 테스트 후보",
            "cj_recent_n": (r.get("mrecent") or {}).get("n") or 0,
            "kp_recent_n": (r.get("mkp") or {}).get("n") or 0,
            "cj_next_rate": (r.get("mrecent") or {}).get("next_rate"),
            "kp_next_rate": (r.get("mkp") or {}).get("next_rate"),
            "cj_avg_arrival": _avg_to_hhmm((r.get("mrecent") or {}).get("avg_min")),
            "kp_avg_arrival": _avg_to_hhmm((r.get("mkp") or {}).get("avg_min")),
        })
    return recommendations


def latest_branch_rep_for_customer(db_path: str, customer_code: str) -> tuple[str, str]:
    with _connect(db_path) as con:
        for table in ("carrier_switch_shipments", "shipments"):
            exists = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                continue
            if table == "carrier_switch_shipments":
                row = con.execute(
                    """
                    SELECT dept_name branch_name, rep_name sales_rep_name
                    FROM carrier_switch_shipments
                    WHERE customer_code=? AND COALESCE(rep_name,'')<>''
                    ORDER BY ship_date DESC
                    LIMIT 1
                    """,
                    (customer_code,),
                ).fetchone()
            else:
                row = con.execute(
                    """
                    SELECT dept_name branch_name, rep_name sales_rep_name
                    FROM shipments
                    WHERE customer_code=? AND COALESCE(rep_name,'')<>''
                    ORDER BY ship_date DESC
                    LIMIT 1
                    """,
                    (customer_code,),
                ).fetchone()
            if row:
                return row["branch_name"] or "", row["sales_rep_name"] or ""
    return "", ""


def _avg_to_hhmm(value: Any) -> str:
    if value is None or value == "":
        return ""
    minutes = int(round(float(value))) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def generate_email_drafts(db_path: str, month: str, *, allowed_grades: tuple[str, ...] = ("A", "B"), out_dir: str | None = None) -> list[dict[str, Any]]:
    with _connect(db_path) as con:
        placeholders = ",".join("?" for _ in allowed_grades)
        rows = con.execute(
            f"""
            SELECT r.*, COALESCE(m.email, '') email
            FROM monthly_carrier_recommendations r
            LEFT JOIN sales_rep_email_map m
              ON m.sales_rep_name=r.sales_rep_name
             AND (COALESCE(m.branch_name,'')=COALESCE(r.branch_name,'') OR COALESCE(m.branch_name,'')='')
             AND m.active=1
            WHERE r.month=?
              AND r.recommended_carrier='CJ'
              AND r.grade IN ({placeholders})
            ORDER BY r.sales_rep_name, r.branch_name, r.grade, r.customer_name
            """,
            (month, *allowed_grades),
        ).fetchall()
        grouped: dict[tuple[str, str, str], list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            key = (row["sales_rep_name"] or "미지정", row["branch_name"] or "", row["email"] or "")
            grouped[key].append(row)
        drafts = []
        for (rep, branch, email), items in grouped.items():
            subject = f"[배송품질 분석] {month} CJ 예외 발송 테스트 후보 안내"
            body = render_email_body(month, rep, branch, items)
            draft = {
                "month": month,
                "recipient_email": email,
                "sales_rep_name": rep,
                "branch_name": branch,
                "recommendation_count": len(items),
                "subject": subject,
                "body": body,
            }
            cur = con.execute(
                """
                INSERT INTO recommendation_email_logs(month, recipient_email, sales_rep_name, branch_name, recommendation_count, subject, body_preview, body, status)
                VALUES(?,?,?,?,?,?,?,?, 'draft')
                """,
                (month, email, rep, branch, len(items), subject, body[:500], body),
            )
            draft["log_id"] = int(cur.lastrowid or 0)
            drafts.append(draft)
            if out_dir:
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                safe = "".join(ch if ch.isalnum() else "_" for ch in f"{rep}_{branch}_{email or 'no_email'}")[:80]
                Path(out_dir, f"{month}_{safe}.md").write_text(f"# {subject}\n\nTo: {email or '(이메일 미등록)'}\n\n{body}", encoding="utf-8")
        return drafts


def render_email_body(month: str, rep: str, branch: str, rows: list[sqlite3.Row]) -> str:
    lines = [
        "안녕하세요.",
        "",
        f"{month} 출고 및 최근 배송품질 데이터를 기준으로, 일부 거래처에서 CJ대한통운 이용 시 익일배송률 또는 평균 도착시간이 양호하게 나타났습니다.",
        "아래 거래처는 일괄 변경이 아니라 2주간 CJ 예외 발송 테스트 대상으로 검토 부탁드립니다.",
        "",
        "| 등급 | 거래처 | 최근 CJ | 우체국 | 사유 |",
        "|---|---|---:|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['grade']} | {r['customer_name']} | {r['cj_recent_n']}건 / {_pct(r['cj_next_rate'])} / {r['cj_avg_arrival']} | "
            f"{r['kp_recent_n']}건 / {_pct(r['kp_next_rate'])} / {r['kp_avg_arrival']} | {r['reason']} |"
        )
    lines += [
        "",
        "※ 산정 기준: 금요일 출고, 공휴일 전일 출고, 제주/도서산간 등 익일배송 보장 곤란 조건은 제외했습니다.",
        "※ 본 안내는 테스트 권고이며, 거래처 특이사항이 있는 경우 기존 운영 기준을 우선 적용해 주세요.",
    ]
    return "\n".join(lines)


def _pct(value: Any) -> str:
    if value is None or value == "":
        return ""
    return f"{float(value) * 100:.1f}%"
