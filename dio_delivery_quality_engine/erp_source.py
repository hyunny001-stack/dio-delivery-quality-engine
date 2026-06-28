from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def fetch_erp_rows(start: str, end: str, endpoint: str | None = None, api_key: str | None = None, timeout: int = 30) -> dict[str, Any]:
    """Fetch ERP domestic shipment rows for a date range.

    Environment variables are used only when this optional ERP pull step is requested:
    - ERP_API_URL
    - ERP_API_KEY
    """
    endpoint = (endpoint or os.environ.get("ERP_API_URL") or "").strip()
    api_key = api_key if api_key is not None else os.environ.get("ERP_API_KEY", "")
    if not endpoint:
        raise RuntimeError("ERP_API_URL is required for ERP pull mode")

    separator = "&" if "?" in endpoint else "?"
    url = f"{endpoint}{separator}{urlencode({'start_dt': start, 'end_dt': end})}"
    req = Request(url, headers={"x-api-key": api_key or ""})
    with urlopen(req, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))

    if body.get("success") is not True or int(body.get("code", 0)) != 200 or not isinstance(body.get("data"), list):
        raise RuntimeError(f"ERP bad response: code={body.get('code')} success={body.get('success')} total={body.get('total')}")
    return {"start": start, "end": end, "total": body.get("total"), "data": body["data"]}


def write_erp_json(start: str, end: str, out: str, endpoint: str | None = None, api_key: str | None = None) -> None:
    data = fetch_erp_rows(start, end, endpoint=endpoint, api_key=api_key)
    Path(out).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
