#!/usr/bin/env python3
"""
mcp_server.py — MCP Server for Vocational Training Intelligence Hub
====================================================================
Author:  Ridhi Jain  |  Date: 24 June 2026
Project: Microsoft Elevate AICTE Internship — SPRINT 6

Exposes Power BI analytics to AI agents via FastMCP.
Tools: get_district_performance, run_pareto_analysis, find_capacity_gaps
Resources: intelligence://district_trends, telemetry://logs
Prompts: analyze_vocational_gap
"""

import csv, json, logging, os, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastmcp import FastMCP
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False
    class FastMCP:
        def __init__(self, name: str): self.name = name
        def tool(self): return lambda f: f
        def resource(self, uri: str): return lambda f: f
        def prompt(self, name: str): return lambda f: f
        def run(self): pass

mcp = FastMCP("Vocational Training Intelligence Hub")

DATA_DIR = Path(__file__).parent
APPRENTICESHIP_CSV = DATA_DIR / "ridhijain608_17728151714584544.csv"
CTS_CSV = DATA_DIR / "ridhijain608_17728151856929433.csv"

logging.basicConfig(level=logging.INFO,
    format='{"timestamp":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
log = logging.getLogger("mcp.vocational")

def load_apprenticeship_data() -> List[Dict[str, Any]]:
    rows = []
    if not APPRENTICESHIP_CSV.exists(): return rows
    with open(APPRENTICESHIP_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({"state": row.get("State","").strip(), "district": row.get("District","").strip(),
                    "year": row.get("Year","").strip(),
                    "enrolled": int(row.get("Apprentices Enrolled In The Program (UOM:Number), Scaling Factor:1",0) or 0),
                    "centers": int(row.get("Training Centers Established For The Program (UOM:Number), Scaling Factor:1",0) or 0)})
            except (ValueError, KeyError): continue
    log.info(f"Loaded {len(rows)} apprenticeship records")
    return rows

def load_cts_data() -> List[Dict[str, Any]]:
    rows = []
    if not CTS_CSV.exists(): return rows
    with open(CTS_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({"state": row.get("State","").strip(), "district": row.get("District","").strip(),
                    "year": row.get("Year","").strip(),
                    "enrolled": int(row.get("Enrolled Trainees Under Craftsmen Training Scheme (UOM:Number), Scaling Factor:1",0) or 0),
                    "institutes": int(row.get("Institutes For Training Under Craftsmen Training Scheme Scheme (UOM:Number), Scaling Factor:1",0) or 0),
                    "seating_capacity": int(row.get("Seating Capacity Of Training Centers (UOM:Number), Scaling Factor:1",0) or 0)})
            except (ValueError, KeyError): continue
    log.info(f"Loaded {len(rows)} CTS records")
    return rows

@mcp.tool()
def get_district_performance(district: str) -> dict:
    """Return enrollment, capacity, and utilization for a district."""
    app_data = load_apprenticeship_data(); cts_data = load_cts_data()
    dl = district.strip().lower()
    ad = [r for r in app_data if dl in r["district"].lower()]
    cd = [r for r in cts_data if dl in r["district"].lower()]
    ae = sum(r["enrolled"] for r in ad); ac = sum(r["centers"] for r in ad)
    ce = sum(r["enrolled"] for r in cd); cc = sum(r["seating_capacity"] for r in cd); ci = sum(r["institutes"] for r in cd)
    util = (ce / cc * 100) if cc > 0 else 0
    years = sorted(set(r["year"] for r in cd))
    yoy = {}
    for i in range(1, len(years)):
        pe = sum(r["enrolled"] for r in cd if r["year"]==years[i-1])
        cu = sum(r["enrolled"] for r in cd if r["year"]==years[i])
        if pe > 0: yoy[years[i]] = round(((cu-pe)/pe)*100, 1)
    return {"district": district, "matched_districts": len(set(r["district"] for r in ad+cd)),
        "apprenticeship": {"enrolled": ae, "centers": ac, "records": len(ad)},
        "cts": {"enrolled": ce, "capacity": cc, "institutes": ci, "utilization_pct": round(util,2), "records": len(cd)},
        "yoy_trend_pct": yoy, "data_years": years}

@mcp.tool()
def run_pareto_analysis(dataset: str = "apprenticeship") -> dict:
    """Compute Pareto: what % districts drive 80% enrollment."""
    data = load_apprenticeship_data() if dataset == "apprenticeship" else load_cts_data()
    de: Dict[str, int] = defaultdict(int)
    for r in data: de[r["district"]] += r["enrolled"]
    sd = sorted(de.items(), key=lambda x: x[1], reverse=True)
    total = sum(v for _, v in sd)
    cum = 0; pc = 0; pp = 0.0
    for i, (_, v) in enumerate(sd):
        cum += v
        if cum >= 0.8 * total and pc == 0: pc = i+1; pp = (pc/len(sd))*100
    return {"dataset": dataset, "total_districts": len(sd), "total_enrollment": total,
        "top_5": [{"district": d, "enrollment": e, "pct": round((e/total)*100, 2)} for d, e in sd[:5]],
        "pareto": {"districts_for_80pct": pc, "pct_of_all": round(pp, 2)},
        "distribution": {"mean": round(total/len(sd),1), "median": sd[len(sd)//2][1], "max": sd[0][1], "min": sd[-1][1],
            "zero_enrollment": sum(1 for _, v in sd if v == 0)}}

@mcp.tool()
def find_capacity_gaps(utilization_threshold: float = 95.0) -> dict:
    """Find districts with CTS utilization above threshold."""
    cts = load_cts_data()
    dm: Dict[str, Dict[str, int]] = defaultdict(lambda: {"enrolled": 0, "capacity": 0})
    for r in cts: d = r["district"]; dm[d]["enrolled"] += r["enrolled"]; dm[d]["capacity"] += r["seating_capacity"]
    gaps = []
    for dist, m in dm.items():
        if m["capacity"] == 0: continue
        u = (m["enrolled"]/m["capacity"])*100
        if u >= utilization_threshold:
            gap = max(0, m["enrolled"]-m["capacity"])
            gaps.append({"district": dist, "enrolled": m["enrolled"], "capacity": m["capacity"],
                "utilization_pct": round(u,2), "seats_shortfall": gap, "recommended_new_seats": int(gap*1.2)})
    gaps.sort(key=lambda x: x["utilization_pct"], reverse=True)
    return {"threshold": utilization_threshold, "above_threshold": len(gaps), "total_districts": len(dm),
        "critical": gaps[:20], "total_seats_recommended": sum(g["recommended_new_seats"] for g in gaps)}

@mcp.resource("intelligence://district_trends")
def district_trends() -> str:
    """Expose normalized historical dataset trends as read-only JSON."""
    ad = load_apprenticeship_data(); cd = load_cts_data()
    ys = defaultdict(lambda: {"app": 0, "cts_enr": 0, "cts_cap": 0})
    for r in ad: ys[r["year"]]["app"] += r["enrolled"]
    for r in cd: ys[r["year"]]["cts_enr"] += r["enrolled"]; ys[r["year"]]["cts_cap"] += r["seating_capacity"]
    return json.dumps({"summary": {"app_records": len(ad), "cts_records": len(cd),
        "app_total": sum(r["enrolled"] for r in ad), "cts_total": sum(r["enrolled"] for r in cd)},
        "yearly": {y: {"app_enrollment": d["app"], "cts_enrollment": d["cts_enr"],
            "cts_capacity": d["cts_cap"], "utilization_pct": round((d["cts_enr"]/d["cts_cap"])*100,2) if d["cts_cap"]>0 else 0}
            for y, d in sorted(ys.items())},
        "generated_at": datetime.now(timezone.utc).isoformat()}, indent=2)

@mcp.resource("telemetry://logs")
def telemetry_logs() -> str:
    """Expose system health, data freshness, and tool catalog."""
    return json.dumps({"server": "Vocational Training Intelligence Hub",
        "status": "healthy" if (APPRENTICESHIP_CSV.exists() and CTS_CSV.exists()) else "degraded",
        "data": {"app_csv": APPRENTICESHIP_CSV.exists(), "cts_csv": CTS_CSV.exists()},
        "tools": ["get_district_performance", "run_pareto_analysis", "find_capacity_gaps"],
        "resources": ["intelligence://district_trends", "telemetry://logs"],
        "prompts": ["analyze_vocational_gap"],
        "timestamp": datetime.now(timezone.utc).isoformat()}, indent=2)

@mcp.prompt("analyze_vocational_gap")
def analyze_vocational_gap(state: str, year: str = "2021") -> str:
    """Prompt template for LLM-based capacity gap analysis."""
    return f"""You are a vocational training policy analyst for India's Skill India Mission.
Analyze the capacity gap for {state} in FY {year}:
1. Current enrollment, capacity, utilization %
2. Districts above 95% utilization — how many seats needed?
3. 3 actionable policy interventions ranked by impact
4. Benchmark vs national average and identify one similar state that solved the gap
Use get_district_performance and find_capacity_gaps tools for data."""

if __name__ == "__main__":
    log.info("MCP server: Vocational Training Intelligence Hub")
    if HAS_FASTMCP: mcp.run()
    else: print(json.dumps({"status": "ready", "install": "pip install fastmcp"}, indent=2))
