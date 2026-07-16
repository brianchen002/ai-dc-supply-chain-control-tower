"""Synthetic dataset generator — AI Data Center Supply Chain Control Tower.

ALL DATA IS FICTIONAL. Real manufacturer names are used for realism only;
quantities, prices, lead times and performance figures are simulated.

Design (docs/PROJECT_UPGRADE_AUDIT.md — retained from the OpsPilot generator
architecture):
  * Causal, not random: a ground-truth delay process drives outcomes.
    P(delay) rises with supplier capacity utilization, constrained categories,
    historical supplier delay rate, ocean freight, congested origins, large
    orders and thin inventory buffers. Long-lead gear (transformers,
    generators, chillers) is structurally riskier against fixed site dates.
    The ML models later have to *rediscover* this process from the data.
  * As-of-order-time features are stored separately from outcome fields so
    downstream modeling can avoid target leakage.
  * Deterministic: one RANDOM_SEED; dates anchor to run date.

Usage:
    python -m src.data_generation.generate [--force]
Outputs:
    data/synthetic/{purchase_orders,suppliers,sites,equipment_catalog,demand_plan}.csv
"""
from __future__ import annotations

import argparse
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

from config.settings import (
    BUYERS, CATEGORY_MIX, CONGESTED_ORIGINS, CONTRACT_TYPES, DELAY_LOGIT,
    DELAY_MAGNITUDE_MULTIPLIERS, DELAY_MAGNITUDE_SCALE, EQUIPMENT,
    FREIGHT_FORWARDERS, HISTORY_MONTHS, INCOTERMS, MANUFACTURER_ORIGIN,
    MILESTONE_PINNED_SHARE, N_PURCHASE_ORDERS, RANDOM_SEED,
    SHIPPING_TRANSIT_DAYS, SITES, SITE_TIGHTNESS_DAYS, SYNTHETIC_DIR,
)

QTY_RANGE = {
    "GPU Servers": (8, 64), "NVIDIA GPU Systems": (2, 16),
    "InfiniBand Switches": (10, 80), "Network Equipment": (10, 120),
    "Transformers": (1, 3), "Chillers": (2, 8), "Cooling Systems": (5, 40),
    "UPS Systems": (2, 12), "Power Distribution Units": (20, 300),
    "Storage Systems": (2, 12), "Racks": (20, 200), "Backup Generators": (1, 4),
}

BUFFER_RANGE = {  # inventory buffer days by criticality of category
    "critical": (5, 20), "high": (10, 30), "medium": (20, 45), "low": (30, 60),
}

DISTRIBUTORS = [
    ("SUP-D01", "WWT", "United States",
     ["GPU Servers", "Network Equipment", "Storage Systems", "Racks"]),
    ("SUP-D02", "Insight Enterprises", "United States",
     ["Network Equipment", "Storage Systems", "Power Distribution Units", "Racks"]),
    ("SUP-D03", "Graybar", "United States",
     ["Power Distribution Units", "UPS Systems"]),
]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-x))


def build_suppliers(rng: random.Random) -> pd.DataFrame:
    rows, sid = [], 1
    for cat, spec in EQUIPMENT.items():
        for mfg in spec["manufacturers"]:
            existing = next((r for r in rows if r["supplier_name"] == mfg), None)
            if existing:
                existing["categories"] = existing["categories"] + "|" + cat
                continue
            constrained = spec["constrained"]
            util = rng.uniform(0.86, 0.97) if constrained else rng.uniform(0.58, 0.88)
            # Utilization causally degrades OTD and inflates historical delays
            otd = max(0.55, min(0.97, 1.05 - 0.55 * util + rng.uniform(-0.06, 0.06)))
            rows.append({
                "supplier_id": f"SUP-{sid:03d}", "supplier_name": mfg,
                "country": MANUFACTURER_ORIGIN[mfg], "categories": cat,
                "capacity_utilization": round(util, 3),
                "on_time_delivery_rate": round(otd, 3),
                "historical_delay_rate": round(1 - otd + rng.uniform(0.0, 0.05), 3),
                "quality_score": round(rng.uniform(0.82, 0.99), 3),
            })
            sid += 1
    for code, name, country, cats in DISTRIBUTORS:
        util = rng.uniform(0.6, 0.8)
        otd = max(0.6, min(0.96, 1.05 - 0.55 * util + rng.uniform(-0.05, 0.05)))
        rows.append({
            "supplier_id": code, "supplier_name": name, "country": country,
            "categories": "|".join(cats),
            "capacity_utilization": round(util, 3),
            "on_time_delivery_rate": round(otd, 3),
            "historical_delay_rate": round(1 - otd + rng.uniform(0.0, 0.04), 3),
            "quality_score": round(rng.uniform(0.85, 0.99), 3),
        })
    return pd.DataFrame(rows)


def build_sites(today: date) -> pd.DataFrame:
    rows = []
    for code, metro, country, region, mw, gpus, phase, months_out, install_mo in SITES:
        required = today + timedelta(days=int(months_out * 30.4))
        install = required - timedelta(days=int(install_mo * 30.4))
        rows.append({
            "data_center_site": code, "metro": metro, "country": country,
            "region": region, "planned_compute_capacity_mw": mw,
            "planned_gpu_capacity": gpus, "project_phase": phase,
            "required_capacity_date": required.isoformat(),
            "installation_start_date": install.isoformat(),
        })
    return pd.DataFrame(rows)


def build_catalog(rng: random.Random) -> pd.DataFrame:
    rows = []
    for cat, spec in EQUIPMENT.items():
        for t in spec["types"]:
            for mfg in spec["manufacturers"]:
                rows.append({
                    "equipment_category": cat, "equipment_type": t,
                    "manufacturer": mfg,
                    "part_number": f"{mfg[:3].upper()}-{''.join(w[0] for w in cat.split())}-{rng.randint(1000, 9999)}",
                    "unit_cost_usd": round(rng.uniform(*spec["unit_cost"]), 0),
                    "criticality": spec["criticality"],
                    "supply_constrained": spec["constrained"],
                })
    return pd.DataFrame(rows)


def build_purchase_orders(rng, nprng, suppliers, sites, catalog, today) -> pd.DataFrame:
    cat_suppliers = {
        cat: suppliers[suppliers["categories"].str.contains(cat, regex=False)]
        for cat in EQUIPMENT
    }
    site_weights = [s[4] for s in SITES]
    site_codes = [s[0] for s in SITES]
    cats, weights = zip(*CATEGORY_MIX.items())
    qty_p75 = {c: QTY_RANGE[c][0] + 0.75 * (QTY_RANGE[c][1] - QTY_RANGE[c][0])
               for c in EQUIPMENT}

    rows = []
    for i in range(N_PURCHASE_ORDERS):
        cat = rng.choices(cats, weights=weights)[0]
        spec = EQUIPMENT[cat]
        part = catalog[catalog["equipment_category"] == cat].sample(1, random_state=nprng.integers(1e9)).iloc[0]
        sup_pool = cat_suppliers[cat]
        sup = sup_pool.sample(1, random_state=nprng.integers(1e9)).iloc[0]

        # Order date: volume ramps up over the 18-month window. Long-lead
        # categories are ordered earlier (procurement plans them first).
        m = HISTORY_MONTHS * np.sqrt(rng.random())
        if spec["base_lead"] > 250:
            m *= 0.55
        m = int(np.clip(m, 0, HISTORY_MONTHS - 0.01))
        days_ago = int((HISTORY_MONTHS - m) * 30.4 - rng.uniform(0, 30))
        order_dt = today - timedelta(days=max(1, days_ago))

        qty = rng.randint(*QTY_RANGE[cat])
        unit_cost = round(float(part["unit_cost_usd"]) * rng.uniform(0.92, 1.08), 2)
        mode = rng.choices(list(spec["modes"]), weights=list(spec["modes"].values()))[0]
        origin = MANUFACTURER_ORIGIN[part["manufacturer"]]
        site = rng.choices(site_codes, weights=site_weights)[0]
        site_row = sites[sites["data_center_site"] == site].iloc[0]
        buffer_days = rng.randint(*BUFFER_RANGE[spec["criticality"]])
        alt = rng.random() < spec["alt_prob"]

        planned_lead = int(max(20, nprng.normal(spec["base_lead"], spec["lead_spread"] * 0.6)
                               + (8 if mode == "Ocean" else -4 if mode == "Air" else 0)
                               + 12 * (qty > qty_p75[cat])))

        # Required-on-site date: either planned against lead time (with a
        # buffer that is sometimes too thin), or pinned to site installation
        # milestones — where per-site schedule tightness bites.
        if rng.random() > MILESTONE_PINNED_SHARE:
            slack = rng.uniform(-0.05, 0.45) * planned_lead
            required = order_dt + timedelta(days=int(planned_lead + slack))
        else:
            stagger = {"critical": -20, "high": 10, "medium": 25, "low": 40}[spec["criticality"]]
            required = (date.fromisoformat(site_row["installation_start_date"])
                        + timedelta(days=stagger + rng.randint(-20, 30)
                                    - SITE_TIGHTNESS_DAYS[site]))
            required = max(required, order_dt + timedelta(days=25))

        # ---- Ground-truth delay process (the causal heart) ----
        L = DELAY_LOGIT
        logit = (L["intercept"]
                 + L["capacity_utilization"] * max(0.0, sup["capacity_utilization"] - 0.75) * 4
                 + L["constrained_category"] * spec["constrained"]
                 + L["historical_delay_rate"] * sup["historical_delay_rate"]
                 + L["ocean_mode"] * (mode == "Ocean")
                 + L["congested_origin"] * CONGESTED_ORIGINS[origin]
                 + L["large_order"] * (qty > qty_p75[cat])
                 + L["low_buffer"] * (buffer_days < 15)
                 + nprng.normal(0, 0.35))
        delayed = rng.random() < _sigmoid(logit)
        if delayed:
            # Stressed conditions extend delay duration, not just frequency —
            # this is the signal the lead-time regressor must recover.
            M = DELAY_MAGNITUDE_MULTIPLIERS
            stress = (1.0
                      + M["capacity_utilization"] * max(0.0, sup["capacity_utilization"] - 0.75) * 4
                      + M["congested_origin"] * CONGESTED_ORIGINS[origin]
                      + M["constrained_category"] * spec["constrained"])
            median = max(5.0, planned_lead * DELAY_MAGNITUDE_SCALE * stress)
            true_delay = int(nprng.lognormal(np.log(median), 0.45))
        else:
            true_delay = int(min(0, nprng.normal(-2, 3)))  # small early deliveries

        committed = order_dt + timedelta(days=planned_lead)
        true_arrival = committed + timedelta(days=true_delay)
        transit = rng.randint(*SHIPPING_TRANSIT_DAYS[mode])
        prod_start = order_dt + timedelta(days=rng.randint(5, 20))
        ship_dt = true_arrival - timedelta(days=transit)

        # ---- Status & visible ETA as of today ----
        cancelled = rng.random() < 0.015
        delivered = true_arrival <= today and not cancelled
        if delivered:
            proc_status, ship_status = "Delivered", "Delivered"
            actual_delivery = true_arrival
            current_eta = true_arrival
            customs = "Cleared" if origin != "United States" else "Not required"
            receipt = "Received"
        elif cancelled:
            proc_status, ship_status = "Cancelled", "Not Shipped"
            actual_delivery, current_eta = None, None
            customs, receipt = "N/A", "N/A"
        else:
            # Partial visibility: the known slip grows as the order progresses
            progress = float(np.clip((today - order_dt).days / max(planned_lead, 1), 0.05, 1.0))
            known_slip = max(0, int(true_delay * progress + nprng.normal(0, 4))) if true_delay > 0 else 0
            current_eta = committed + timedelta(days=known_slip)
            actual_delivery = None
            if today < prod_start:
                proc_status, ship_status = "Ordered", "Not Shipped"
            elif today < ship_dt:
                proc_status, ship_status = "In Production", "Not Shipped"
            else:
                proc_status = "Shipped"
                near_arrival = (current_eta - today).days <= 6
                ship_status = ("Customs" if (origin != "United States" and near_arrival
                                             and rng.random() < 0.5)
                               else "Delayed" if known_slip > 7 else "In Transit")
            customs = ("Not required" if origin == "United States"
                       else "In clearance" if ship_status == "Customs" else "Pending")
            receipt = "Pending"

        actual_lead = (actual_delivery - order_dt).days if delivered else None
        current_expected_lead = ((current_eta - order_dt).days
                                 if current_eta is not None else None)
        delay_days = ((current_eta or actual_delivery) - committed).days if not cancelled else None

        rows.append({
            # PO information
            "purchase_order_id": f"PO-{1000 + i}",
            "purchase_order_date": order_dt.isoformat(),
            "supplier_id": sup["supplier_id"], "supplier_name": sup["supplier_name"],
            "equipment_category": cat, "equipment_type": part["equipment_type"],
            "manufacturer": part["manufacturer"], "part_number": part["part_number"],
            "order_quantity": qty, "unit_cost": unit_cost,
            "total_order_value": round(qty * unit_cost, 2),
            "currency": "EUR" if origin == "Germany" else "USD",
            "procurement_status": proc_status, "buyer": rng.choice(BUYERS),
            "contract_type": rng.choice(CONTRACT_TYPES),
            # Delivery & logistics
            "production_start_date": prod_start.isoformat(),
            "supplier_committed_date": committed.isoformat(),
            "original_eta": committed.isoformat(),
            "current_eta": current_eta.isoformat() if current_eta else None,
            "actual_delivery_date": actual_delivery.isoformat() if actual_delivery else None,
            "required_on_site_date": required.isoformat(),
            "shipment_status": ship_status, "shipping_mode": mode,
            "origin_country": origin,
            "destination_country": site_row["country"],
            "destination_site": site,
            "freight_forwarder": rng.choice(FREIGHT_FORWARDERS),
            "customs_status": customs, "incoterm": rng.choice(INCOTERMS),
            "warehouse_receipt_status": receipt,
            "tracking_update_date": (today - timedelta(days=rng.randint(0, 4))).isoformat(),
            # Lead time & risk inputs (as-of-order-time features)
            "planned_lead_time_days": planned_lead,
            "current_expected_lead_time_days": current_expected_lead,
            "actual_lead_time_days": actual_lead,
            "delay_days": delay_days,
            "supplier_capacity_utilization": sup["capacity_utilization"],
            "supplier_on_time_delivery_rate": sup["on_time_delivery_rate"],
            "historical_supplier_delay_rate": sup["historical_delay_rate"],
            "equipment_criticality": spec["criticality"],
            "alternative_supplier_available": alt,
            "inventory_buffer_days": buffer_days,
            "deployment_dependency": ("High" if spec["criticality"] == "critical"
                                      else "Medium" if spec["criticality"] == "high" else "Low"),
            # Infrastructure planning
            "data_center_site": site,
            "planned_compute_capacity_mw": site_row["planned_compute_capacity_mw"],
            "planned_gpu_capacity": site_row["planned_gpu_capacity"],
            "project_phase": site_row["project_phase"],
            "required_capacity_date": site_row["required_capacity_date"],
            "installation_start_date": site_row["installation_start_date"],
            # Ground truth (simulation-only; used for labels on delivered POs)
            "_true_arrival": true_arrival.isoformat(),
        })

    df = pd.DataFrame(rows)
    df["purchase_order_id"] = [f"PO-{1000 + i}" for i in range(len(df))]

    # Post-derivations
    df["lead_time_variance"] = df.groupby("supplier_id")["planned_lead_time_days"].transform(
        lambda s: round(s.std(ddof=0) if len(s) > 1 else 0.0, 1))
    spend = df.groupby(["equipment_category", "supplier_id"])["total_order_value"].transform("sum")
    cat_spend = df.groupby("equipment_category")["total_order_value"].transform("sum")
    df["supply_concentration"] = (spend / cat_spend).round(3)
    # Label: did/will the PO miss its required-on-site date (ground truth)
    df["missed_required_date"] = (
        pd.to_datetime(df["_true_arrival"]) > pd.to_datetime(df["required_on_site_date"])
    ).astype(int)
    df.loc[df["procurement_status"] == "Cancelled", "missed_required_date"] = 0
    return df


def build_demand_plan(sites: pd.DataFrame, today: date) -> pd.DataFrame:
    """Planned equipment demand per site/category/month, scaled by capacity."""
    per_mw = {"GPU Servers": 3.2, "NVIDIA GPU Systems": 0.8, "InfiniBand Switches": 2.0,
              "Network Equipment": 2.4, "Transformers": 0.02, "Chillers": 0.06,
              "Cooling Systems": 0.8, "UPS Systems": 0.12, "Power Distribution Units": 6.0,
              "Storage Systems": 0.35, "Racks": 6.5, "Backup Generators": 0.03}
    rows = []
    for _, s in sites.iterrows():
        req = date.fromisoformat(s["required_capacity_date"])
        horizon = max(3, min(12, (req - today).days // 30))
        for cat, k in per_mw.items():
            total_units = max(1, int(k * s["planned_compute_capacity_mw"]))
            remaining = int(total_units * 0.45)  # portion still to be delivered
            for j in range(horizon):
                month = (today.replace(day=1) + timedelta(days=32 * j)).replace(day=1)
                share = (j + 1) / sum(range(1, horizon + 1))  # back-loaded ramp
                rows.append({
                    "data_center_site": s["data_center_site"],
                    "equipment_category": cat,
                    "month": month.isoformat(),
                    "planned_units": max(0, int(remaining * share)),
                })
    return pd.DataFrame(rows)


def build_supplier_emails(pos: pd.DataFrame, rng: random.Random, today: date) -> list[dict]:
    """~12 synthetic supplier/logistics emails referencing REAL open POs.

    Self-consistency rule (same as everywhere else): every PO id, SKU and
    supplier named in an email exists in the dataset, so entity linking in
    the extraction layer is verifiable.
    """
    open_pos = pos[~pos["procurement_status"].isin(["Delivered", "Cancelled"])]
    domain = lambda s: s.lower().replace(" ", "").replace("+", "") + ".example.com"  # noqa: E731

    def pick(cat: str, n: int = 1) -> pd.DataFrame:
        subset = open_pos[open_pos["equipment_category"] == cat]
        return subset.sample(min(n, len(subset)), random_state=rng.randint(0, 10**6))

    emails, eid = [], 1

    def add(sender, subject, body, days_ago):
        nonlocal eid
        emails.append({
            "email_id": f"MSG-{eid:03d}", "from_addr": sender, "subject": subject,
            "received": (today - timedelta(days=days_ago)).isoformat(),
            "body": body.strip(),
        })
        eid += 1

    # 1–2: lead-time slip with explicit PO references
    for _, r in pick("InfiniBand Switches", 1).iterrows():
        add(f"allocation@{domain(r['supplier_name'])}",
            f"Revised outlook — {r['equipment_type']} orders",
            f"""Dear Meridian procurement team,

Due to a production line changeover for {r['equipment_type']} ({r['part_number']}),
shipments against {r['purchase_order_id']} are expected to slip approximately 2 weeks
beyond the committed date. We apologize for the disruption and will confirm a
recovery schedule by Friday.""", 1)
    for _, r in pick("GPU Servers", 1).iterrows():
        add(f"orders@{domain(r['supplier_name'])}",
            f"Delivery update: {r['purchase_order_id']}",
            f"""Hello,

Heads-up that {r['purchase_order_id']} ({r['order_quantity']}x {r['equipment_type']})
is running about 10 days behind plan due to component shortages on our side.
Revised packing list to follow.""", 2)

    # 3–4: slip referencing SKU/type only (linking must infer the POs)
    for _, r in pick("Cooling Systems", 1).iterrows():
        add(f"support@{domain(r['supplier_name'])}",
            "CDU production constraint notice",
            f"""To our valued customers,

We are experiencing a supply constraint affecting {r['equipment_type']} units
(part family {r['part_number'][:7]}). Open orders may be delayed by up to 3 weeks.
Our team will follow up with order-level impacts next week.""", 3)
    for _, r in pick("Backup Generators", 1).iterrows():
        add(f"projects@{domain(r['supplier_name'])}",
            "Genset assembly backlog — schedule risk",
            f"""Dear partner,

Engine supply issues have pushed our {r['equipment_type']} assembly backlog out by
roughly 30 days. Orders placed after March are most affected.""", 4)

    # 5: allocation cut (category-level)
    for _, r in pick("NVIDIA GPU Systems", 1).iterrows():
        add(f"allocation@{domain(r['supplier_name'])}",
            "Q3 allocation adjustment",
            f"""Allocation notice:

Your Q3 allocation for {r['equipment_type']} systems has been reduced by 15%
due to upstream HBM supply constraints. Affected order quantities will be
confirmed in the next allocation cycle.""", 2)

    # 6–7: expedite confirmations (good news — negative impact)
    for _, r in pick("Transformers", 1).iterrows():
        add(f"logistics@{domain(r['supplier_name'])}",
            f"Expedite confirmed — {r['purchase_order_id']}",
            f"""Good news: we secured an earlier test slot and {r['purchase_order_id']}
({r['equipment_type']}) is now tracking 3 weeks ahead of the revised schedule.
Updated shipping documents attached.""", 5)
    for _, r in pick("UPS Systems", 1).iterrows():
        add(f"orders@{domain(r['supplier_name'])}",
            f"Pull-in accepted for {r['purchase_order_id']}",
            f"""Confirming the requested pull-in: {r['purchase_order_id']} will ship
7 days earlier than committed.""", 6)

    # 8–9: logistics disruptions
    add("notices@kuehne-nagel.example.com",
        "Port congestion advisory — trans-Pacific eastbound",
        """Advisory: vessel bunching at Kaohsiung and LA/Long Beach is adding
7-10 days to trans-Pacific ocean transits this month. Shipments from Taiwan
origins are most affected. Air capacity remains available at premium rates.""", 1)
    add("customs@dbschenker.example.com",
        "Customs hold — inbound consignment",
        f"""One inbound consignment for {pick('Chillers', 1).iloc[0]['purchase_order_id'] if len(pick('Chillers', 1)) else 'PO-1000'}
is held for customs valuation review at the port of entry. Typical clearance
for this review type is 5-8 business days.""", 2)

    # 10: quality hold
    for _, r in pick("Power Distribution Units", 1).iterrows():
        add(f"quality@{domain(r['supplier_name'])}",
            f"QA hold: {r['part_number']}",
            f"""Quality notification: a torque-spec deviation was found in a recent
{r['equipment_type']} lot ({r['part_number']}). Outbound shipments are held
pending re-inspection, estimated 6 days.""", 3)

    # 11–12: noise (extractor should classify as NO_IMPACT)
    add("billing@wwt.example.com", "Invoice reminder — August statement",
        "Friendly reminder that invoice batch #88231 is due at the end of the month.", 4)
    add("events@vertiv.example.com", "Webinar: liquid cooling best practices",
        "Join our webinar next Thursday on rear-door heat exchanger deployment patterns.", 5)

    return emails


def generate_all(force: bool = False, verbose: bool = True) -> dict:
    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)
    marker = SYNTHETIC_DIR / "purchase_orders.csv"
    if marker.exists() and not force:
        if verbose:
            print("Synthetic data already exists — use --force to regenerate.")
        return {}

    rng = random.Random(RANDOM_SEED)
    nprng = np.random.default_rng(RANDOM_SEED)
    today = date.today()

    suppliers = build_suppliers(rng)
    sites = build_sites(today)
    catalog = build_catalog(rng)
    pos = build_purchase_orders(rng, nprng, suppliers, sites, catalog, today)
    demand = build_demand_plan(sites, today)

    emails = pd.DataFrame(build_supplier_emails(pos, rng, today))
    out = {"suppliers": suppliers, "sites": sites, "equipment_catalog": catalog,
           "purchase_orders": pos, "demand_plan": demand,
           "supplier_emails": emails}
    for name, df in out.items():
        df.to_csv(SYNTHETIC_DIR / f"{name}.csv", index=False)
    if verbose:
        print(f"Generated → {SYNTHETIC_DIR}")
        for name, df in out.items():
            print(f"  {name:<20} {len(df):>6} rows")
        open_pos = pos[~pos["procurement_status"].isin(["Delivered", "Cancelled"])]
        print(f"  open POs: {len(open_pos)} · delivered: {(pos['procurement_status'] == 'Delivered').sum()}"
              f" · miss-rate (all): {pos['missed_required_date'].mean():.0%}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    generate_all(force=ap.parse_args().force)
