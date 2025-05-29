# affordance_validator.py
from __future__ import annotations
import json, math, re
from pathlib import Path
from typing import Dict, List, Tuple

import parse_cam_formulary as cam



# ─────────────────────────────────────────────────────────────────────────────
# Process plan parsing
# ─────────────────────────────────────────────────────────────────────────────

TOL_PCT = 0.05     # Soft limits

_STEP_HDR = re.compile(
    r"""
    ^\s*
    (?:\#+\s*)?          # markdown header (optional)
    (\d+)                # step number
    [\.\)]\s*
    (?:\*\*|__)?         # opening bold (optional)
    ([^*\n]+?)           # TITLE (group-2 !)
    (?:\*\*|__)?         # closing bold (optional)
    \s*$
    """,
    re.MULTILINE | re.VERBOSE,
)

_NUM = re.compile(r"([\d\.]+)")



# ─────────────────────────────────────────────────────────────────────────────
# Tool‑coating compatibility table per ISO class
# ─────────────────────────────────────────────────────────────────────────────

_COATING_REQ = {
    "P": ["alcrn", "hyb. alcrn", "altin", "hyb. altin", "tialn", "tiain"],
    "M": ["alcrn", "hyb. alcrn", "altin", "hyb. altin", "tialn", "tiain"],
    "K": ["alcrn", "hyb. alcrn", "altin", "hyb. altin", "tialn", "tiain"],
    "N": ["uncoated"],  # aluminium alloys: only uncoated
    "S": ["alcrn", "hyb. alcrn", "altin", "hyb. altin", "tialn", "tiain"],
    "H": ["alcrn", "hyb. alcrn", "altin", "hyb. altin", "tialn", "tiain"],
}



# ─────────────────────────────────────────────────────────────────────────────
# Low‑level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _strategy(text: str, op_line: str = "") -> str:
    txt = f"{text} {op_line}".lower()
    if any(k in txt for k in ("rough", "roughing")):
        return "roughing"
    if any(k in txt for k in ("finish", "finishing", "swarf", "semi-finish", "contour", "contouring", "taper", "tapering", "profile", "profiling")):
        return "finishing"
    if any(k in txt for k in ("drill", "bore", "ream", "reamer", "tapping", "tap")):
        return "drilling"
    if any(k in txt for k in ("slot", "slotting", "slitting", "groove", "grooving", "keyway", "keywaying", "pocket", "pocketing")):
        return "slotting"
    return "roughing"


def parse_txt_plan(text: str) -> List[Dict]:
    """Parse a human‑written process plan and extract a list of machining steps."""
    steps: List[Dict] = []
    headers = list(_STEP_HDR.finditer(text))
    for i, h in enumerate(headers):
        blk  = text[h.end(): headers[i + 1].start() if i + 1 < len(headers) else len(text)]
        step_title = h.group(2).strip()
        op_match  = re.search(r"Operation\s*:\s*([^\n]+)", blk, re.I)
        op_line   = op_match.group(1) if op_match else ""
        step = {
            "step": step_title,
            "strategy": _strategy(step_title, op_line)   # <── passa anche op_line
        }

        patt = {
            "tool_id": r"Tool.*ID:\s*(\d+)",
            "tool_dia": r"D\s*=\s*(\d+\.?\d*)\s*mm",
            "n":        r"Spindle Speed.*?:\s*(\d+)\s*RPM",
            "vf":       r"Feedrate.*?:\s*(\d+)\s*mm/min",
            "ap":       r"Depth/Pass.*?:\s*(\d+\.?\d*)\s*mm",
            "ae":       r"Side Engagement.*?:\s*(\d+\.?\d*)\s*mm",
        }

        for k, pat in patt.items():
            m = re.search(pat, blk, re.I)
            if m:
                step[k] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
        if "tool_id" in step:
            steps.append(step)
            
        # print(f"[DEBUG] Parsed {len(steps)} steps.") # debug - comment this line if not needed

    return steps


def _find_tool(tid: int, tools: List[Dict]) -> Dict:
    """Return the tool dict with *id == tid* or an empty dict."""
    return next((t for t in tools if t.get("id") == tid), {})

def _calc_values(step: Dict, tool: Dict) -> Dict[str, float]:
    """Compute derived cutting parameters for the given *step* and *tool*.""" 
    D  = tool.get("dia", step.get("tool_dia", 0)) or 0
    z  = tool.get("flutes", 1)
    n  = step.get("n", 0)
    vf = step.get("vf", 0)
    Vc = math.pi * D * n / 1000 if D else 0      # cutting speed (m/min)
    fz = vf / (n * z) if n and z else 0          # mm / tooth
    fn = vf / n          if n else 0             # mm / rev
    return {"D": D, "z": z, "Vc": Vc, "fz": fz, "fn": fn}

def _loc_to_mm(loc_val, tool_dia: float) -> float:
    """Convert a LOC value ("2xD", "12 mm", 15) to absolute millimetres."""   
    if isinstance(loc_val, (int, float)): return float(loc_val)
    if not isinstance(loc_val, str): return math.inf
    s, m = loc_val.lower(), _NUM.search(loc_val)
    if not m: return math.inf
    num = float(m.group(1))
    return num * tool_dia if "x" in s and "d" in s else num

def _out_of_band(value, lo, hi):
    """Return *True* if *value* lies outside the soft range [lo, hi] ±TOL_PCT."""
    lo_soft = lo * (1 - TOL_PCT)
    hi_soft = hi * (1 + TOL_PCT)
    return value < lo_soft or value > hi_soft



# ─────────────────────────────────────────────────────────────────────────────
# Automatic correction engine
# ─────────────────────────────────────────────────────────────────────────────

def _mid(lo: float, hi: float) -> float:
    """Return a value inside [lo, hi]. Falls back to *lo* if range is 0."""
    return lo if hi <= lo else (lo + hi) / 2.0


def suggest_corrections(step: Dict, machine: Dict, mat_tag: str, tool: Dict) -> Dict:
    """Generate a *minimal viable* set of parameter corrections.

    Heuristic approach:
      • Pick mid‑range values for Vc, fz and engagement ratios
      • Respect machine capability limits (rpm, Vf)
      • Respect tool limitations (LOC)
    """
    calc = _calc_values(step, tool)
    D    = calc["D"];  z = calc["z"]
    if not D: return {}
    z = calc["z"] or 1  # avoid division by zero

    lim = cam.get_limits_for(mat_tag,
                             operation="drilling" if step["strategy"] == "drilling" else "milling",
                             drill_diam=step.get("tool_dia"))

    # 1) RPM target via cutting‑speed range
    strat = step["strategy"]
    Vc_lo, Vc_hi = lim["Vc"]
    if strat == "slotting":
        Vc_lo, Vc_hi = Vc_lo * 0.4, Vc_hi * 0.7  # more conservative for slotting
    elif strat == "finishing":
        Vc_lo, Vc_hi = Vc_lo * 1.1, Vc_hi * 1.2  # slightly higher for finishing

    Vc_target = _mid(Vc_lo, Vc_hi)
    n_target = Vc_target * 1000 / (math.pi * D)
    n_target = int(min(n_target, machine.get("max_spindle_rpm", n_target)))
 
    # 2) Feed‑rate via fz
    if strat == "drilling":
        fn_target = _mid(*lim["f_n"]) or 0.05  # default for micro drills
        vf_target = int(fn_target * n_target)
    else:
        fz_range = lim["fz_finish"] if strat == "finishing" else lim["fz_rough"]
        fz_target = _mid(*fz_range) or 0.05
        vf_target = int(fz_target * n_target * z)

    vf_target = int(min(vf_target, machine.get("max_feed_rate", vf_target)))

    # 3) Engagement ratios
    eng = cam.get_engagement_limits(strat)
    ap_ratio = _mid(*eng["ap_d"])
    ae_ratio = _mid(*eng["ae_d"])
    ap_target = round(ap_ratio * D, 2)
    ae_target = round(ae_ratio * D, 2)

    # Respect LOC (Length Of Cut)
    loc_mm = _loc_to_mm(tool.get("loc", math.inf), D)
    if ap_target > loc_mm:
        ap_target = round(max(loc_mm * 0.8, 0.1), 2)

    return {
        "tool_id": step.get("tool_id"),
        "n": n_target,
        "vf": vf_target,
        "ap": ap_target,
        "ae": ae_target,
    }



# ─────────────────────────────────────────────────────────────────────────────
# Validation + suggestion in one pass
# ─────────────────────────────────────────────────────────────────────────────

def validate_step(step: Dict, machine: Dict, mat_tag: str, tools: List[Dict]) -> Tuple[bool, List[str]]:
    """Validate a single machining *step*.

    Returns *(ok, issues)* where *ok* is a bool and *issues* is a list of
    human‑readable strings describing any problems found.
    """

    tool  = _find_tool(step.get("tool_id"), tools)

    # 0) skip engagement‐ratio checks for drilling, ballmills or face mills
    ttype = tool.get("type", "").lower()
    is_face  = "facemill" in ttype or "face mill" in ttype
    skip_ae = step["strategy"] == "drilling" or ttype == "ballmill" or is_face
    
    calc  = _calc_values(step, tool)
    loc_mm= _loc_to_mm(tool.get("loc", math.inf), calc["D"])

    issues: List[str] = []
    ok = True

    # Machine capability checks ------------------------------------------------
    if step.get("n", 0)  > machine.get("max_spindle_rpm", 9e9):
        issues.append("rpm > machine limit")
        ok=False
    if step.get("vf", 0) > machine.get("max_feed_rate", 9e9):
        issues.append("feed > machine limit")
        ok=False
    if step.get("ap", 0) > loc_mm:
        issues.append("ap exceeds tool LOC")
        ok=False
    
    # Material specific limits --------------------------------------------------
    lim  = cam.get_limits_for(mat_tag,
                              operation="drilling" if step["strategy"] == "drilling" else "milling",
                              drill_diam=step.get("tool_dia"))

    strat = step["strategy"]

    # Feed check ----------------------------------------------------------------
    if strat == "drilling":
        fn_lo, fn_hi = lim["f_n"]
        fn_val = calc["fn"]
        if fn_lo and _out_of_band(fn_val, fn_lo, fn_hi):
            issues.append(
                f"f_n {fn_val:.3f} mm/rev outside [{fn_lo:.3f},{fn_hi:.3f}]±{TOL_PCT*100:.0f}%"
            )
            ok = False
    else:
        fz_lo, fz_hi = lim["fz_finish"] if strat == "finishing" else lim["fz_rough"]
        if fz_lo and _out_of_band(calc["fz"], fz_lo, fz_hi):
            issues.append(
                f"f_z {calc['fz']:.3f} mm/tooth outside [{fz_lo:.3f},{fz_hi:.3f}]±{TOL_PCT*100:.0f}%"
            )
            ok = False
    
    # Cutting speed check -------------------------------------------------------   
    Vc_lo, Vc_hi = lim["Vc"]
    if strat == "slotting":
        # reduce by 30–60% → allow 40…70% of nominal
        Vc_lo, Vc_hi = Vc_lo * 0.4, Vc_hi * 0.7
    elif strat == "finishing":
        # increase by ~10–20%
        Vc_lo, Vc_hi = Vc_lo * 1.1, Vc_hi * 1.2

    if _out_of_band(calc["Vc"], Vc_lo, Vc_hi):
        issues.append(
            f"Vc {calc['Vc']:.0f} m/min outside [{Vc_lo:.0f},{Vc_hi:.0f}]±{TOL_PCT*100:.0f}%"
        )
        ok = False

    # Engagement ratio checks ---------------------------------------------------
    eng = cam.get_engagement_limits(strat)
    if calc["D"] and not skip_ae:
        apR = step.get("ap", 0) / calc["D"]
        aeR = step.get("ae", 0) / calc["D"]
        ap_lo, ap_hi = eng["ap_d"]
        ae_lo, ae_hi = eng["ae_d"]
       
        if _out_of_band(apR, ap_lo, ap_hi):
            issues.append(f"ap/D {apR:.2f} outside [{ap_lo:.2f},{ap_hi:.2f}]")
        if not (aeR == 1.0 and (step["strategy"] == "drilling" or is_face)):
            if _out_of_band(aeR, ae_lo, ae_hi):
               issues.append(f"ae/D {aeR:.2f} outside [{ae_lo:.2f},{ae_hi:.2f}]")

    # Tool‑coating check --------------------------------------------------------
    coating = tool.get("coating", "").lower()
    reqs    = _COATING_REQ.get(mat_tag, [])
    if mat_tag == "N":
        if coating and coating != "uncoated":
            issues.append(f"tool coating “{tool.get('coating')}” not suitable for Al alloys")
    else:
        if reqs and not any(r in coating for r in reqs):
            issues.append(f"tool coating “{tool.get('coating')}” not suitable for ISO-{mat_tag}")

    # Bore diameter vs tool diameter for drilling ------------------------------
    if strat == "drilling" and "bore_diameter" in step:
        if calc["D"] > step["bore_diameter"]:
            issues.append(
                f"tool D={calc['D']} mm exceeds bore Ø={step['bore_diameter']} mm"
            )

    return ok, issues



# ─────────────────────────────────────────────────────────────────────────────
# Pretty‑print summary of validation
# ─────────────────────────────────────────────────────────────────────────────

def _flagged(label: str, val, faulty_keys: set[str]) -> str:
    mark = "⚠️" if label.lower() in faulty_keys else "✅"
    return f"{label}: {val} {mark}"

def summarize_step(step: dict, ok: bool, issues: list[str]) -> str:
    status = "✅" if ok else "❌"
    faulty = {w.lower().split()[0] for w in issues}
    calc   = step.get("_calc", {})
    line1  = (
        f"• Tool {step.get('tool_id')} (D={calc.get('D', '?')} mm, z={calc.get('z', '?')}) | "
        f"n={step.get('n', '?')} rpm | "
        f"Vf={step.get('vf', '?')} mm/min | "
        f"Vc={calc.get('Vc', 0):.0f} m/min | "
        f"f_z={calc.get('fz', 0):.3f} | f_n={calc.get('fn', 0):.3f}"
    )
    line2 = (
        f"• ap={step.get('ap', '?')} mm | ae={step.get('ae', '?')} mm | "
        f"strategy={step['strategy']}"
    )
    out = [f"{status} {step['step']}"]
    out.append("   " + _flagged("tool", line1, faulty))
    out.append("   " + _flagged("cut",  line2, faulty))
    for i in issues:
        out.append(f"   - ⚠️ {i}")
    return "\n".join(out)

def summarize_validation(plan_txt: str, machine: dict, material: str) -> str:
    tag   = cam.infer_material_tag(material)
    tools = machine.get("tool_library", [])
    blocks = []
    for st in parse_txt_plan(plan_txt):
        ok, iss = validate_step(st, machine, tag, tools)[:2]
        st["_calc"] = _calc_values(st, _find_tool(st.get("tool_id"), tools))
        blocks.append(summarize_step(st, ok, iss))
    return "\n\n".join(blocks)



# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse, sys
    p = argparse.ArgumentParser()
    p.add_argument("plan")
    p.add_argument("machine")
    p.add_argument("material")
    a = p.parse_args()
    plan = Path(a.plan).read_text(encoding="utf-8")
    mach = json.loads(Path(a.machine).read_text())
    print(summarize_validation(plan, mach, a.material))