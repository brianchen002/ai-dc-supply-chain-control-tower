"""Ask the Control Tower — natural language → SQL over the analytics DB.

LIVE mode: Claude writes a single SELECT against the documented schema; the
query is sanitized (read-only connection, SELECT-only, denylist, row cap)
and executed; a second small call interprets the result.
OFFLINE mode: a curated library of common operational questions with
prepared SQL — honest about the boundary (free-form NL→SQL needs the API).

Safety layers (all enforced regardless of what the model returns):
  1. sqlite opened read-only (`mode=ro`) — writes are impossible.
  2. single statement, must start with SELECT/WITH, denylist keywords.
  3. LIMIT 200 appended when missing.
"""
from __future__ import annotations

import json
import re
import sqlite3

import pandas as pd

from config.settings import DB_PATH
from src.llm.prompts import CONTROL_TOWER_SYSTEM

SCHEMA_NOTES = """\
Tables (SQLite):
purchase_orders(purchase_order_id, purchase_order_date, supplier_id, supplier_name,
  equipment_category, equipment_type, manufacturer, part_number, order_quantity,
  unit_cost, total_order_value, currency, procurement_status
  [Ordered|In Production|Shipped|Delivered|Cancelled], buyer, contract_type,
  production_start_date, supplier_committed_date, original_eta, current_eta,
  actual_delivery_date, required_on_site_date, shipment_status, shipping_mode,
  origin_country, destination_country, destination_site, freight_forwarder,
  customs_status, incoterm, planned_lead_time_days, current_expected_lead_time_days,
  actual_lead_time_days, delay_days, supplier_capacity_utilization,
  equipment_criticality [critical|high|medium|low], inventory_buffer_days,
  data_center_site, project_phase, predicted_lead_days, predicted_delivery_date,
  delay_probability, risk_score, risk_level [Critical|High|Moderate|Low],
  top_risk_drivers, recommended_action, missed_required_date)
suppliers(supplier_id, supplier_name, country, categories, capacity_utilization,
  on_time_delivery_rate, historical_delay_rate, quality_score)
sites(data_center_site, metro, country, region, planned_compute_capacity_mw,
  planned_gpu_capacity, project_phase, required_capacity_date, installation_start_date)
supplier_scorecard(supplier_name, active_pos, open_value, on_time_delivery_rate,
  avg_realized_delay_days, avg_lead_time_days, capacity_utilization,
  supplier_risk_score, ...)
site_readiness(data_center_site, metro, readiness_score, readiness_status,
  delivered_pct, at_risk_pos, value_at_risk, critical_outstanding, ...)
alerts(alert_id, severity, alert_type, entity, message, created_at)
supply_gap(equipment_category, site, month, planned_demand, expected_deliveries, supply_gap)
Notes: dates are ISO strings — use date()/julianday(). "Open PO" means
procurement_status NOT IN ('Delivered','Cancelled').
"""

NL2SQL_USER = """\
Write ONE SQLite SELECT statement answering the question. Return ONLY the SQL
(no prose, no fences). Prefer clear column aliases; aggregate when the
question implies it; include ORDER BY when ranking; LIMIT 200 max.

{schema}

Question: {question}
"""

INTERPRET_USER = """\
Question: {question}
SQL used: {sql}
Result (first rows, CSV):
{preview}

In 1-2 sentences, state the direct answer with the key numbers. If the result
is empty, say what that means operationally.
"""

DENY = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|pragma|vacuum|replace)\b", re.I)

CANNED = {
    "Top 10 highest-risk open POs": (
        """SELECT purchase_order_id, supplier_name, equipment_category, destination_site,
                  total_order_value, delay_probability, risk_score, risk_level
           FROM purchase_orders
           WHERE procurement_status NOT IN ('Delivered','Cancelled')
           ORDER BY risk_score DESC LIMIT 10""",
        "The riskiest open orders, ranked by composite risk score."),
    "Which suppliers' realized lead times are worsening?": (
        """WITH halves AS (
             SELECT supplier_name,
                    AVG(CASE WHEN purchase_order_date >= date('now','-5 months')
                             THEN actual_lead_time_days END) AS recent,
                    AVG(CASE WHEN purchase_order_date < date('now','-5 months')
                             THEN actual_lead_time_days END) AS earlier,
                    COUNT(*) AS delivered
             FROM purchase_orders WHERE procurement_status = 'Delivered'
             GROUP BY supplier_name)
           SELECT supplier_name, ROUND(earlier,0) AS earlier_avg_days,
                  ROUND(recent,0) AS recent_avg_days,
                  ROUND(recent - earlier,0) AS worsening_days, delivered
           FROM halves WHERE recent IS NOT NULL AND earlier IS NOT NULL
           ORDER BY worsening_days DESC LIMIT 15""",
        "Suppliers whose recent deliveries take longer than their earlier ones."),
    "Open value by data center and category": (
        """SELECT destination_site, equipment_category,
                  ROUND(SUM(total_order_value),0) AS open_value, COUNT(*) AS pos
           FROM purchase_orders
           WHERE procurement_status NOT IN ('Delivered','Cancelled')
           GROUP BY 1,2 ORDER BY open_value DESC LIMIT 40""",
        "Where the open spend is concentrated."),
    "POs required on site within 30 days but not yet shipped": (
        """SELECT purchase_order_id, supplier_name, equipment_category, destination_site,
                  required_on_site_date, procurement_status, risk_level, total_order_value
           FROM purchase_orders
           WHERE procurement_status IN ('Ordered','In Production')
             AND julianday(required_on_site_date) <= julianday('now') + 30
           ORDER BY required_on_site_date LIMIT 50""",
        "Time-critical orders that have not even shipped yet."),
    "Critical equipment still outstanding per site": (
        """SELECT destination_site, COUNT(*) AS critical_open,
                  ROUND(SUM(total_order_value),0) AS value,
                  SUM(CASE WHEN risk_level IN ('Critical','High') THEN 1 ELSE 0 END) AS at_risk
           FROM purchase_orders
           WHERE procurement_status NOT IN ('Delivered','Cancelled')
             AND equipment_criticality = 'critical'
           GROUP BY 1 ORDER BY at_risk DESC""",
        "Critical-path exposure by site."),
    "Monthly order value trend": (
        """SELECT strftime('%Y-%m', purchase_order_date) AS month,
                  COUNT(*) AS pos, ROUND(SUM(total_order_value),0) AS value
           FROM purchase_orders WHERE procurement_status != 'Cancelled'
           GROUP BY 1 ORDER BY 1""",
        "Procurement volume ramp over time."),
    "Single-source concentration hotspots": (
        """SELECT equipment_category, supplier_name,
                  ROUND(MAX(supply_concentration)*100,0) AS pct_of_category_spend,
                  ROUND(SUM(total_order_value),0) AS value
           FROM purchase_orders
           GROUP BY 1,2 HAVING pct_of_category_spend > 50
           ORDER BY pct_of_category_spend DESC""",
        "Categories where one supplier holds most of the spend."),
    "Forwarder usage and delayed shipments": (
        """SELECT freight_forwarder, COUNT(*) AS shipments,
                  SUM(CASE WHEN shipment_status='Delayed' THEN 1 ELSE 0 END) AS delayed
           FROM purchase_orders
           WHERE shipment_status != 'Not Shipped'
           GROUP BY 1 ORDER BY delayed DESC""",
        "Forwarder mix and where delays cluster."),
}


def sanitize_sql(sql: str) -> str:
    """Raise ValueError unless `sql` is one safe SELECT; return cleaned SQL."""
    cleaned = re.sub(r"^```(sql)?|```$", "", sql.strip(), flags=re.M).strip().rstrip(";")
    if ";" in cleaned:
        raise ValueError("multiple statements are not allowed")
    head = re.sub(r"^\s*--.*$", "", cleaned, flags=re.M).lstrip()
    if not re.match(r"^(select|with)\b", head, re.I):
        raise ValueError("only SELECT queries are allowed")
    if DENY.search(cleaned):
        raise ValueError("write/DDL keywords are not allowed")
    if not re.search(r"\blimit\s+\d+", cleaned, re.I):
        cleaned += " LIMIT 200"
    return cleaned


def run_query(sql: str) -> pd.DataFrame:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(sql, conn)
    finally:
        conn.close()


def ask(question: str, client) -> dict:
    """Live NL→SQL. Returns {sql, df, answer, mode} (df None on failure)."""
    if not client.is_live:
        return {"sql": None, "df": None, "mode": "offline",
                "answer": "Free-form questions need live AI (set ANTHROPIC_API_KEY). "
                          "Pick a prepared question from the library instead."}
    try:
        sql = client.complete(
            CONTROL_TOWER_SYSTEM,
            NL2SQL_USER.format(schema=SCHEMA_NOTES, question=question),
            max_tokens=600)
        sql = sanitize_sql(sql)
        df = run_query(sql)
        preview = df.head(12).to_csv(index=False)
        answer = client.complete(
            CONTROL_TOWER_SYSTEM,
            INTERPRET_USER.format(question=question, sql=sql, preview=preview),
            max_tokens=250)
        return {"sql": sql, "df": df, "answer": answer, "mode": "live"}
    except ValueError as e:
        return {"sql": None, "df": None, "mode": "live",
                "answer": f"Query rejected by the safety layer: {e}"}
    except Exception as e:
        return {"sql": None, "df": None, "mode": "live",
                "answer": f"Couldn't answer that ({type(e).__name__}). Try rephrasing."}


def ask_canned(name: str) -> dict:
    sql, blurb = CANNED[name]
    df = run_query(sanitize_sql(sql))
    return {"sql": sql, "df": df, "mode": "offline",
            "answer": f"{blurb} ({len(df)} rows)"}
