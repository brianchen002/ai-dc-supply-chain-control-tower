"""Inbox intelligence — unstructured supplier emails → structured risk events.

This is where an LLM earns its keep in a supply chain product: the earliest
delay signals live in *text* (supplier emails, forwarder advisories), not in
any database field. This module turns that text into structured events,
links them to real purchase orders, and quantifies the risk impact.

Two extraction modes, same output contract:
  * LIVE    — Claude extracts events under a strict JSON schema.
  * OFFLINE — a rule/regex extractor (keywords, impact parsing, PO-id and
              SKU matching). Honest degradation: weaker on paraphrase,
              identical downstream behavior.

Event schema:
  {email_id, event_type, supplier, matched_by, impact_days, confidence,
   affected_pos: [...], summary}
"""
from __future__ import annotations

import json
import re
import sqlite3

import numpy as np
import pandas as pd

from src.llm.prompts import CONTROL_TOWER_SYSTEM

EVENT_TYPES = ["LEAD_TIME_SLIP", "ALLOCATION_CUT", "EXPEDITE_CONFIRMED",
               "LOGISTICS_DISRUPTION", "QUALITY_HOLD", "NO_IMPACT"]

EXTRACT_USER = """\
Extract supply chain risk events from the emails below.

Return ONLY a JSON array (no prose). One object per email:
{{
  "email_id": "...",
  "event_type": one of {types},
  "supplier": supplier name if identifiable else null,
  "sku_or_family": part number / equipment keyword if named else null,
  "explicit_po_ids": ["PO-1234", ...] only if literally present,
  "impact_days": integer (negative = earlier/pull-in; 0 if none/unknown),
  "confidence": 0.0-1.0,
  "summary": one sentence
}}

Rules: never invent PO ids; marketing/billing emails are NO_IMPACT;
"N weeks" = N*7 days; expedites get negative impact_days.

Emails:
{emails_json}
"""


# ---------------------------------------------------------------------------
# Offline rule-based extractor
# ---------------------------------------------------------------------------

_KEYWORDS = [
    ("EXPEDITE_CONFIRMED", r"expedite|pull-?in|ahead of|ship.{0,15}earlier|earlier than committed"),
    ("ALLOCATION_CUT", r"allocation.{0,40}(reduced|adjust|cut)|quota"),
    ("LOGISTICS_DISRUPTION", r"port|congestion|vessel|customs|clearance|transit"),
    ("QUALITY_HOLD", r"quality|qa hold|re-?inspection|deviation|damaged"),
    ("LEAD_TIME_SLIP", r"slip|delay|behind|pushed|backlog|constraint|shortage"),
]

_IMPACT = [
    (re.compile(r"(\d+)\s*weeks?", re.I), 7),
    (re.compile(r"(\d+)\s*(?:business\s*)?days?", re.I), 1),
    (re.compile(r"(\d+)-(\d+)\s*(?:business\s*)?days?", re.I), 1),
]


def _rule_extract(email: dict, suppliers: list[str]) -> dict:
    text = f"{email['subject']}\n{email['body']}"
    low = text.lower()

    event = "NO_IMPACT"
    for etype, pat in _KEYWORDS:
        if re.search(pat, low):
            event = etype
            break
    if re.search(r"invoice|webinar|billing|statement", low) and "delay" not in low:
        event = "NO_IMPACT"

    impact = 0
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*(business\s*)?days?", low)
    if m:
        impact = (int(m.group(1)) + int(m.group(2))) // 2
    else:
        m = re.search(r"(\d+)\s*weeks?", low)
        if m:
            impact = int(m.group(1)) * 7
        else:
            m = re.search(r"(\d+)\s*(business\s*)?days?", low)
            if m:
                impact = int(m.group(1))
    if event == "EXPEDITE_CONFIRMED":
        impact = -abs(impact)
    if event == "NO_IMPACT":
        impact = 0

    sender_key = email["from_addr"].split("@")[-1].split(".")[0]
    supplier = next((s for s in suppliers
                     if s.lower().replace(" ", "").replace("+", "") == sender_key), None)

    pos_ids = re.findall(r"PO-\d{4}", text)
    return {
        "email_id": email["email_id"], "event_type": event, "supplier": supplier,
        "sku_or_family": None, "explicit_po_ids": pos_ids,
        "impact_days": impact,
        "confidence": 0.9 if pos_ids else (0.6 if supplier else 0.4),
        "summary": email["subject"],
    }


# ---------------------------------------------------------------------------
# Linking + risk impact (shared by both modes)
# ---------------------------------------------------------------------------

def _link_pos(event: dict, email: dict, open_pos: pd.DataFrame) -> tuple[list[str], str]:
    if event.get("explicit_po_ids"):
        valid = [p for p in event["explicit_po_ids"]
                 if p in set(open_pos["purchase_order_id"])]
        if valid:
            return valid, "explicit PO reference"

    text = f"{email['subject']} {email['body']}"
    cand = open_pos
    if event.get("supplier"):
        cand = cand[cand["supplier_name"] == event["supplier"]]
    # match by part number or equipment-type keyword appearing in the email
    hits = cand[
        cand["part_number"].map(lambda p: str(p)[:7] in text)
        | cand["equipment_type"].map(
            lambda t: any(w in text for w in str(t).split() if len(w) > 4))
    ]
    if len(hits):
        return hits["purchase_order_id"].head(5).tolist(), "supplier + SKU/type match"
    if event.get("supplier") and len(cand):
        return cand["purchase_order_id"].head(5).tolist(), "supplier match (broad)"
    return [], "unlinked"


def _risk_shift(p0: float, impact_days: int) -> float:
    p0 = float(np.clip(p0, 0.01, 0.99))
    delta = np.sign(impact_days) * np.log1p(abs(impact_days) / 30) * 1.2
    return float(1 / (1 + np.exp(-(np.log(p0 / (1 - p0)) + delta))))


def process_inbox(conn: sqlite3.Connection, client) -> pd.DataFrame:
    """Dashboard entry point: read tables from the DB, then extract."""
    emails_df = pd.read_sql("SELECT * FROM supplier_emails", conn)
    open_pos = pd.read_sql(
        """SELECT purchase_order_id, supplier_name, equipment_category, equipment_type,
                  part_number, total_order_value, delay_probability, current_eta,
                  required_on_site_date
           FROM purchase_orders
           WHERE procurement_status NOT IN ('Delivered','Cancelled')""", conn)
    suppliers = pd.read_sql(
        "SELECT supplier_name FROM suppliers", conn)["supplier_name"].tolist()
    return extract_events(emails_df, open_pos, suppliers, client)


def extract_events(emails_df: pd.DataFrame, open_pos: pd.DataFrame,
                   suppliers: list[str], client) -> pd.DataFrame:
    """Pure function: emails + open-PO context → structured event table."""
    emails = emails_df.to_dict("records")

    if client.is_live:
        try:
            raw = client.complete(
                CONTROL_TOWER_SYSTEM,
                EXTRACT_USER.format(
                    types=EVENT_TYPES,
                    emails_json=json.dumps(emails, ensure_ascii=False)),
                max_tokens=2000)
            raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M)
            events = json.loads(raw)
            assert isinstance(events, list)
            mode = "live"
        except Exception:
            events = [_rule_extract(e, suppliers) for e in emails]
            mode = "offline (live parse failed)"
    else:
        events = [_rule_extract(e, suppliers) for e in emails]
        mode = "offline"

    email_by_id = {e["email_id"]: e for e in emails}
    rows = []
    for ev in events:
        email = email_by_id.get(ev.get("email_id"))
        if email is None:
            continue
        linked, how = ([], "n/a — no impact") if ev["event_type"] == "NO_IMPACT" \
            else _link_pos(ev, email, open_pos)
        affected = open_pos[open_pos["purchase_order_id"].isin(linked)]
        impact = int(ev.get("impact_days") or 0)
        adj = [
            {"po": r["purchase_order_id"],
             "p_before": round(float(r["delay_probability"] or 0.05), 3),
             "p_after": round(_risk_shift(r["delay_probability"] or 0.05, impact), 3),
             "value": r["total_order_value"]}
            for _, r in affected.iterrows()
        ] if impact != 0 else []
        rows.append({
            "email_id": ev["email_id"],
            "event_type": ev["event_type"],
            "supplier": ev.get("supplier"),
            "impact_days": impact,
            "confidence": round(float(ev.get("confidence") or 0.5), 2),
            "matched_by": how,
            "affected_pos": json.dumps(linked),
            "risk_adjustments": json.dumps(adj),
            "summary": ev.get("summary") or email["subject"],
            "extraction_mode": mode,
        })
    return pd.DataFrame(rows)
