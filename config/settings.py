"""Central configuration — AI Data Center Supply Chain Control Tower.

Every business constant, causal-generation parameter, scoring weight and
model setting lives here. Docs (docs/, MODEL_DOCUMENTATION.md) reference
these values; change them here and in the docs in the same commit.
"""
import os
from pathlib import Path

# --- Paths -------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
PROCESSED_DIR = DATA_DIR / "processed"
RAW_DIR = DATA_DIR / "raw"
MODELS_DIR = PROCESSED_DIR / "models"
DB_PATH = Path(os.getenv("CT_DB", PROCESSED_DIR / "control_tower.db"))

RANDOM_SEED = 7
N_PURCHASE_ORDERS = 1_650
HISTORY_MONTHS = 18          # order history window ending "today"

# --- Equipment taxonomy --------------------------------------------------------
# category: (types, manufacturers, unit_cost_range_usd, base_lead_days,
#            lead_spread_days, criticality, supply_constrained,
#            alt_supplier_probability, typical shipping modes w/ weights)
EQUIPMENT = {
    "GPU Servers": {
        "types": ["HGX H200 8-GPU server", "MGX GPU server", "4U 8-GPU air-cooled server"],
        "manufacturers": ["Supermicro", "Dell", "Foxconn Industrial"],
        "unit_cost": (180_000, 320_000),
        "base_lead": 110, "lead_spread": 30,
        "criticality": "critical", "constrained": True, "alt_prob": 0.55,
        "modes": {"Air": 0.7, "Ocean": 0.2, "Truck": 0.1},
    },
    "NVIDIA GPU Systems": {
        "types": ["DGX B200 system", "GB200 NVL72 rack system", "HGX B200 baseboard"],
        "manufacturers": ["NVIDIA"],
        "unit_cost": (280_000, 450_000),
        "base_lead": 160, "lead_spread": 40,
        "criticality": "critical", "constrained": True, "alt_prob": 0.0,
        "modes": {"Air": 0.85, "Truck": 0.15},
    },
    "InfiniBand Switches": {
        "types": ["Quantum-2 QM9700 switch", "Quantum-X800 switch", "NDR 400G cable set"],
        "manufacturers": ["NVIDIA Networking"],
        "unit_cost": (28_000, 65_000),
        "base_lead": 140, "lead_spread": 35,
        "criticality": "critical", "constrained": True, "alt_prob": 0.10,
        "modes": {"Air": 0.8, "Ocean": 0.2},
    },
    "Network Equipment": {
        "types": ["800G data center switch", "DCI router", "Top-of-rack switch"],
        "manufacturers": ["Arista", "Cisco", "Juniper"],
        "unit_cost": (18_000, 85_000),
        "base_lead": 85, "lead_spread": 25,
        "criticality": "high", "constrained": False, "alt_prob": 0.85,
        "modes": {"Air": 0.6, "Ocean": 0.3, "Truck": 0.1},
    },
    "Transformers": {
        "types": ["138kV power transformer", "34.5kV pad-mount transformer", "Substation transformer"],
        "manufacturers": ["ABB", "Siemens Energy", "Hyundai Electric"],
        "unit_cost": (450_000, 1_800_000),
        "base_lead": 400, "lead_spread": 90,
        "criticality": "critical", "constrained": True, "alt_prob": 0.15,
        "modes": {"Ocean": 0.7, "Truck": 0.3},
    },
    "Chillers": {
        "types": ["Water-cooled centrifugal chiller", "Air-cooled screw chiller"],
        "manufacturers": ["Carrier", "Trane", "York"],
        "unit_cost": (280_000, 720_000),
        "base_lead": 240, "lead_spread": 60,
        "criticality": "critical", "constrained": False, "alt_prob": 0.45,
        "modes": {"Ocean": 0.55, "Truck": 0.45},
    },
    "Cooling Systems": {
        "types": ["Liquid cooling CDU", "Rear-door heat exchanger", "CRAH unit"],
        "manufacturers": ["Vertiv", "Motivair", "Boyd"],
        "unit_cost": (45_000, 260_000),
        "base_lead": 170, "lead_spread": 45,
        "criticality": "high", "constrained": True, "alt_prob": 0.35,
        "modes": {"Air": 0.35, "Ocean": 0.35, "Truck": 0.3},
    },
    "UPS Systems": {
        "types": ["1.2MW modular UPS", "Static UPS 750kVA", "Lithium-ion battery cabinet"],
        "manufacturers": ["Vertiv", "Eaton", "Schneider Electric"],
        "unit_cost": (90_000, 420_000),
        "base_lead": 160, "lead_spread": 40,
        "criticality": "high", "constrained": False, "alt_prob": 0.6,
        "modes": {"Ocean": 0.45, "Truck": 0.55},
    },
    "Power Distribution Units": {
        "types": ["Overhead busway 1600A", "Floor PDU 400kVA", "Rack PDU metered"],
        "manufacturers": ["Vertiv", "Schneider Electric", "Raritan"],
        "unit_cost": (2_500, 65_000),
        "base_lead": 100, "lead_spread": 30,
        "criticality": "medium", "constrained": False, "alt_prob": 0.8,
        "modes": {"Ocean": 0.3, "Truck": 0.7},
    },
    "Storage Systems": {
        "types": ["All-flash storage array", "Object storage cluster node", "NVMe expansion shelf"],
        "manufacturers": ["Pure Storage", "VAST Data", "Dell"],
        "unit_cost": (130_000, 520_000),
        "base_lead": 80, "lead_spread": 20,
        "criticality": "high", "constrained": False, "alt_prob": 0.75,
        "modes": {"Air": 0.5, "Truck": 0.5},
    },
    "Racks": {
        "types": ["48U server rack", "Seismic rack enclosure", "Cable management kit"],
        "manufacturers": ["Rittal", "Vertiv", "Legrand"],
        "unit_cost": (3_500, 14_000),
        "base_lead": 55, "lead_spread": 15,
        "criticality": "low", "constrained": False, "alt_prob": 0.9,
        "modes": {"Truck": 0.8, "Ocean": 0.2},
    },
    "Backup Generators": {
        "types": ["3MW diesel genset", "2.5MW gas genset", "Day tank & controls package"],
        "manufacturers": ["Caterpillar", "Cummins", "MTU"],
        "unit_cost": (850_000, 2_200_000),
        "base_lead": 330, "lead_spread": 75,
        "criticality": "critical", "constrained": True, "alt_prob": 0.3,
        "modes": {"Ocean": 0.5, "Truck": 0.5},
    },
}

# Share of PO volume by category (GPU/network-heavy buildout)
CATEGORY_MIX = {
    "GPU Servers": 0.16, "NVIDIA GPU Systems": 0.12, "InfiniBand Switches": 0.10,
    "Network Equipment": 0.10, "Storage Systems": 0.08, "Racks": 0.08,
    "Power Distribution Units": 0.08, "Cooling Systems": 0.08, "UPS Systems": 0.07,
    "Chillers": 0.05, "Transformers": 0.04, "Backup Generators": 0.04,
}

MANUFACTURER_ORIGIN = {
    "Supermicro": "Taiwan", "Dell": "Mexico", "Foxconn Industrial": "Taiwan",
    "NVIDIA": "Taiwan", "NVIDIA Networking": "Israel",
    "Arista": "United States", "Cisco": "Mexico", "Juniper": "United States",
    "ABB": "South Korea", "Siemens Energy": "Germany", "Hyundai Electric": "South Korea",
    "Carrier": "United States", "Trane": "United States", "York": "Mexico",
    "Vertiv": "Mexico", "Motivair": "United States", "Boyd": "United States",
    "Eaton": "United States", "Schneider Electric": "Mexico", "Raritan": "Taiwan",
    "Pure Storage": "United States", "VAST Data": "United States",
    "Rittal": "Germany", "Legrand": "Mexico",
    "Caterpillar": "United States", "Cummins": "United States", "MTU": "Germany",
}

# Origins with elevated logistics friction (port congestion / customs complexity)
CONGESTED_ORIGINS = {"Taiwan": 0.35, "South Korea": 0.25, "Germany": 0.20,
                     "Israel": 0.30, "Mexico": 0.10, "United States": 0.0}

SHIPPING_TRANSIT_DAYS = {"Air": (4, 9), "Ocean": (28, 48), "Truck": (2, 7)}
FREIGHT_FORWARDERS = ["DHL Industrial Projects", "Kuehne+Nagel", "DB Schenker",
                      "Expeditors", "Flexport"]
INCOTERMS = ["DDP", "DAP", "FOB", "EXW", "CIF"]
BUYERS = ["A. Whitfield", "J. Marsh", "K. Osei", "L. Tran", "M. Delgado", "S. Park"]
CONTRACT_TYPES = ["Master Supply Agreement", "Spot PO", "Framework Agreement",
                  "Capacity Reservation"]

# --- Data center sites -----------------------------------------------------------
# code, metro, country, region, capacity_mw, gpu_capacity, phase,
# months_until_required_capacity (from today), install_lead_months
SITES = [
    ("ATL-01", "Atlanta, GA",     "United States", "AMER", 120,  80_000, "Phase 2 expansion", 7,  4),
    ("CBUS-02", "New Albany, OH", "United States", "AMER", 200, 150_000, "Phase 1 build",     10, 6),
    ("DFW-03", "Fort Worth, TX",  "United States", "AMER", 150, 100_000, "Phase 1 build",     8,  5),
    ("PHX-04", "Goodyear, AZ",    "United States", "AMER", 250, 180_000, "Greenfield",        14, 8),
    ("RIC-05", "Richmond, VA",    "United States", "AMER",  90,  60_000, "Phase 3 expansion", 5,  3),
    ("DUB-06", "Dublin",          "Ireland",       "EMEA", 100,  70_000, "Phase 1 build",     11, 6),
    ("SIN-07", "Singapore",       "Singapore",     "APAC",  60,  40_000, "Phase 2 expansion", 9,  5),
    ("SLC-08", "Salt Lake City, UT", "United States", "AMER", 180, 130_000, "Greenfield",     16, 9),
]

# --- Causal delay model (ground-truth generator; the ML models must rediscover this)
DELAY_LOGIT = {
    "intercept": -1.9,
    "capacity_utilization": 3.2,     # per unit above 0.75 (scaled ×4)
    "constrained_category": 0.9,
    "historical_delay_rate": 2.6,    # per unit
    "ocean_mode": 0.45,
    "congested_origin": 1.1,         # × origin congestion factor
    "large_order": 0.35,             # qty above category p75
    "low_buffer": 0.5,               # inventory_buffer_days < 15
}
DELAY_MAGNITUDE_SCALE = 0.22         # × planned lead time (lognormal median)
# Stressed conditions extend delay *duration*, not just frequency:
DELAY_MAGNITUDE_MULTIPLIERS = {
    "capacity_utilization": 1.4,     # × max(0, util − 0.75) × 4
    "congested_origin": 0.8,         # × origin congestion factor
    "constrained_category": 0.45,
}

# Per-site schedule tightness (days subtracted from required-on-site dates
# for milestone-pinned POs) — creates realistic site-level risk spread.
SITE_TIGHTNESS_DAYS = {
    "RIC-05": 30, "CBUS-02": 20, "DFW-03": 12, "DUB-06": 15,
    "ATL-01": 5, "PHX-04": 0, "SIN-07": 8, "SLC-08": 0,
}
MILESTONE_PINNED_SHARE = 0.45        # share of POs whose required date is site-driven

# --- Risk scoring (0–100, explainable weights) ------------------------------------
RISK_WEIGHTS = {
    "delay_probability": 0.45,
    "schedule_slack": 0.25,          # how little slack to required-on-site date
    "criticality": 0.15,
    "supply_flexibility": 0.15,      # concentration + no-alternative penalty
}
CRITICALITY_SCORE = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.2}
RISK_BANDS = [(75, "Critical"), (55, "High"), (35, "Moderate"), (0, "Low")]

# --- Readiness scoring --------------------------------------------------------------
READINESS_WEIGHTS = {
    "delivered_pct": 0.30,
    "critical_delivered_pct": 0.35,
    "at_risk_share": 0.20,           # inverted
    "schedule_pressure": 0.15,       # inverted; time to required capacity date
}
READINESS_BANDS = [(75, "Deployment Ready"), (58, "On Track"), (40, "At Risk"), (0, "Critical")]

# --- Modeling -----------------------------------------------------------------------
LEADTIME_TARGET = "actual_lead_time_days"
DELAY_TARGET = "missed_required_date"
TEST_SPLIT_MONTHS = 4                # last N months of delivered POs = test set
HIGH_RISK_RECALL_FLOOR = 0.80        # threshold tuned so recall on positives ≥ this

# --- LLM (ported from OpsPilot) -------------------------------------------------------
DEFAULT_LLM_MODEL = "claude-sonnet-5"
LLM_MODEL_ENV = "LLM_MODEL"
