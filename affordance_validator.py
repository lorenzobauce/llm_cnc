# affordance_validator.py
"""Process‑plan validation and correction engine for LLM_CNC

This module parses a free‑form machining process plan, validates every step
against material / tool tables coming from *parse_cam_formulary.py*, and
(optionally) suggests corrected cutting parameters that keep the same tool but
stay inside the safe operating window of machine + material + tool geometry.

Important behavioural rule requested by the user (2024‑05‑28):
    • **Drilling**   → check / report only feed *per revolution* **fₙ**
    • **Milling**    → check / report only feed *per tooth*       **f_z**

Comments are in English for clarity.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Dict, List, Tuple

import parse_cam_formulary as cam

# ────────────────────────────────────────────────────────────────────────────
# Parsing helpers
# ────────────────────────────────────────────────────────────────────────────

TOL_PCT = 0.05  # soft limits ±5 %

_STEP_HDR = re.compile(
    r"""
    ^\s*
    (?:\#+\s*)?          # optional markdown header marks
    (\d+)                # step number
    [\.\)]\s*
    (?:\*\*|__)?         # optional bold start
    ([^*\n]+?)           # title (group‑2)
    (?:\*\*|__)?         # optional bold end
    \s*$
    """,
    re.MULTILINE | re.VERBOSE,
)

_NUM = re.compile(r"([\d\.]+)")


# ────────────────────────────────────────────────────────────────────────────
# Tool‑coating compatibility table per ISO class
# ────────────────────────────────────────────────────────────────────────────

_COATING_REQ = {
    "P": ["alcrn", "hyb. alcrn", "altin", "hyb. altin", "tialn"],
    "M": ["alcrn", "hyb. alcrn", "altin", "hyb. altin", "tialn"],
    "K": ["alcrn", "hyb. alcrn", "altin", "hyb. altin", "tialn"],
    "N": ["uncoated", "tialn"],
    "S": ["alcrn", "hyb. alcrn", "altin", "hyb. altin", "tialn"],
    "H": ["alcrn", "hyb. alcrn", "altin", "hyb. altin", "tialn"],
}

# ────────────────────────────────────────────────────────────────────────────
# Low‑level helpers
# ────────────────────────────────────────────────────────────────────────────

def _strategy(text: str, op_line: str = "") -> str:
    """Infer machining strategy from free‑text description."""
    txt = f"{text} {op_line}".lower()
    if any(k in txt for k in ("face", "facing", "face-milling", "facemill")):
        return "facing"  
    if any(k in txt for k in ("rough", "roughing")):
        return "roughing"
    if any(
        k in txt
        for k in (
            "finish",
            "finishing",
            "semi-finish",
            "contour",
            "contouring",
            "profile",
            "profiling",
            "taper",
            "tapering",
            "swarf",
        )
    ):
        return "finishing"
    if any(k in txt for k in ("drill", "drilling", "bore", "boring", "ream", "reaming", "tapping", "tap")):
        return "drilling"
    if any(
        k in txt
        for k in (
            "slot",
            "slotting",
            "groove",
            "grooving",
            "keyway",
            "pocket",
            "pocketing",
        )
    ):
        return "slotting"
    return "roughing"


def parse_txt_plan(text: str) -> List[Dict]:
    """Extract machining steps from a markdown‑ish free‑text process plan."""
    steps: List[Dict] = []
    headers = list(_STEP_HDR.finditer(text))
    for i, h in enumerate(headers):
        blk = text[h.end() : headers[i + 1].start() if i + 1 < len(headers) else len(text)]
        title = h.group(2).strip()
        op_match = re.search(r"Operation\s*:\s*([^\n]+)", blk, re.I)
        op_line = op_match.group(1) if op_match else ""
        step: Dict = {
            "step": title,
            "strategy": _strategy(title, op_line),
        }
        # capture basic numeric parameters
        patt = {
            "tool_id": r"Tool.*ID:\s*(\d+)",
            "tool_dia": r"D\s*=\s*(\d+\.?\d*)\s*mm",
            "n": r"Spindle Speed.*?:\s*(\d+)\s*RPM",
            "vf": r"Feedrate.*?:\s*(\d+)\s*mm/min",
            "ap": r"Depth/Pass.*?:\s*(\d+\.?\d*)\s*mm",
            "ae": r"Side Engagement.*?:\s*(\d+\.?\d*)\s*mm",
        }
        for k, pat in patt.items():
            m = re.search(pat, blk, re.I)
            if m:
                step[k] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
        if "tool_id" in step:
            steps.append(step)
    return steps


def _find_tool(tid: int, tools: List[Dict]) -> Dict:
    return next((t for t in tools if t.get("id") == tid), {})


def _calc_values(step: Dict, tool: Dict) -> Dict[str, float]:
    """Compute derived cutting values (Vc, f_z, f_n …)."""
    D = tool.get("dia", step.get("tool_dia", 0)) or 0.0
    z = tool.get("flutes", 1)
    n = step.get("n", 0)
    vf = step.get("vf", 0)
    Vc = math.pi * D * n / 1000 if D else 0  # m/min
    fz = vf / (n * z) if n and z else 0      # mm / tooth
    fn = vf / n if n else 0                  # mm / rev
    return {"D": D, "z": z, "Vc": Vc, "fz": fz, "fn": fn}


def _loc_to_mm(loc_val, tool_dia: float) -> float:
    """Parse LOC specified as a number (mm)."""
    if isinstance(loc_val, (int, float)):
        return float(loc_val)
    return math.inf


def _out_of_band(value: float, lo: float, hi: float) -> bool:
    """Return *True* if *value* lies outside the soft range [lo, hi] ±TOL_PCT."""
    lo_soft = lo * (1 - TOL_PCT)
    hi_soft = hi * (1 + TOL_PCT)
    return value < lo_soft or value > hi_soft


def _mid(lo: float, hi: float) -> float:
    """Mid‑point of a range (falls back to *lo* when lo == hi)."""
    return lo if hi <= lo else (lo + hi) / 2.0

# ────────────────────────────────────────────────────────────────────────────
# Suggestion engine
# ────────────────────────────────────────────────────────────────────────────

def suggest_corrections(step: Dict, machine: Dict, mat_tag: str, tool: Dict) -> Dict:
    """Return a minimal set of parameter fixes to bring the step inside limits."""
    calc = _calc_values(step, tool)
    strat = step["strategy"]
    if strat == "facing":
        ap_tgt = 2.0 if step.get("ap", 0) > 2.0 else step.get("ap", 0)
        return {
            "tool_id": step.get("tool_id"),
            "ap": round(ap_tgt, 2)
        }

    D, z = calc["D"], calc["z"]
    if not D:
        return {}

    strat = step["strategy"]
    lim = cam.get_limits_for(
        mat_tag,
        operation="drilling" if strat == "drilling" else "milling",
        drill_diam=step.get("tool_dia"),
    )

    # 1) Spindle speed via Vc
    Vc_lo, Vc_hi = lim["Vc"]
    if strat == "slotting":
        Vc_lo, Vc_hi = Vc_lo * 0.4, Vc_hi * 0.7
    elif strat == "finishing":
        Vc_lo, Vc_hi = Vc_lo * 1.1, Vc_hi * 1.2
    Vc_tgt = _mid(Vc_lo, Vc_hi)
    n_tgt = Vc_tgt * 1000 / (math.pi * D)
    n_tgt = int(min(n_tgt, machine.get("max_spindle_rpm", n_tgt)))

    # 2) Feed‑rate
    if strat == "drilling":
        fn_lo, fn_hi = lim["f_n"]
        fn_tgt = _mid(fn_lo, fn_hi) or 0.05
        vf_tgt = int(fn_tgt * n_tgt)
    else:
        fz_lo, fz_hi = lim["fz_finish"] if strat == "finishing" else lim["fz_rough"]
        fz_tgt = _mid(fz_lo, fz_hi) or 0.05
        vf_tgt = int(fz_tgt * n_tgt * z)
    vf_tgt = int(min(vf_tgt, machine.get("max_feed_rate", vf_tgt)))

    # 3) Engagement ratios
    eng = cam.get_engagement_limits(strat)
    ap_ratio = _mid(*eng["ap_d"])
    ae_ratio = _mid(*eng["ae_d"])
    ap_tgt = round(ap_ratio * D, 2)
    ae_tgt = round(ae_ratio * D, 2)

    # face-milling: force ap ≤ 2 mm and keep ae as given
    is_face_op = "face" in step.get("step", "").lower()
    if is_face_op and step.get("ap", 0) > 2.0:
        ap_tgt = 2.0

    # respect Length Of Cut
    loc_mm = _loc_to_mm(tool.get("loc", math.inf), D)
    if ap_tgt > loc_mm:
        ap_tgt = round(max(loc_mm * 0.8, 0.1), 2)

    out = {
        "tool_id": step.get("tool_id"),
        "n": n_tgt,
        "vf": vf_tgt,
    }
    if step["strategy"] not in ("drilling", "boring"):
        out["ap"] = ap_tgt
        out["ae"] = ae_tgt
    return out


# ────────────────────────────────────────────────────────────────────────────
# Validation
# ────────────────────────────────────────────────────────────────────────────
def validate_step(
    step: Dict, machine: Dict, mat_tag: str, tools: List[Dict]
) -> Tuple[bool, List[str], Dict]:
    """
    Validate a machining step.

    Returns
    -------
    ok : bool
        True when every check passes.
    issues : list[str]
        Description of each violation.
    suggestions : dict
        Concrete corrected parameters {n, vf, ap, ae, tool_id}; empty when *ok*.
    """

    tool = _find_tool(step.get("tool_id"), tools)
    calc = _calc_values(step, tool)
    strat = step["strategy"]

    # ── 0) special case for facing
    if strat == "facing":
        ok = True
        issues = []
        if step.get("ap", 0) > 2.0:
            issues.append(f"ap {step['ap']} mm exceeds 2 mm limit for facing")
            ok = False
        suggestions = suggest_corrections(step, machine, mat_tag, tool) if not ok else {}
        return ok, issues, suggestions
    
    issues: List[str] = []
    ok = True

    # ── 1) machine capability checks
    if step.get("n", 0) > machine.get("max_spindle_rpm", 9e9):
        issues.append("rpm > machine limit"); ok = False
    if step.get("vf", 0) > machine.get("max_feed_rate", 9e9):
        issues.append("feed > machine limit"); ok = False

    # Length-of-cut check
    # Make sure 'tool' is defined for the current step
    tool_id = step.get("tool_id")
    tool = next((t for t in tools if t.get("id") == tool_id), {})
    loc_mm = tool.get("loc", 0)

    if strat not in ("drilling") and step.get("ap", 0) > loc_mm:
        issues.append("ap exceeds tool LOC"); ok=False

    # ── 2) material + geometry limits (Vc, fz / fn, engagements …)
    lim = cam.get_limits_for(
        mat_tag,
        operation="drilling" if strat == "drilling" else "milling",
        drill_diam=step.get("tool_dia"),
    )

    # feed check (operation aware)
    if strat == "drilling":
        fn_lo, fn_hi = lim["f_n"]
        if fn_lo and _out_of_band(calc["fn"], fn_lo, fn_hi):
            issues.append(
                f"f_n {calc['fn']:.3f} mm/rev outside [{fn_lo:.3f},{fn_hi:.3f}]±{TOL_PCT*100:.0f}%"
            ); ok = False
    else:
        fz_lo, fz_hi = lim["fz_finish"] if strat == "finishing" else lim["fz_rough"]
        if fz_lo and _out_of_band(calc["fz"], fz_lo, fz_hi):
            issues.append(
                f"f_z {calc['fz']:.3f} mm/tooth outside [{fz_lo:.3f},{fz_hi:.3f}]±{TOL_PCT*100:.0f}%"
            ); ok = False

    # cutting-speed check (with strategy multipliers)
    Vc_lo, Vc_hi = lim["Vc"]
    if strat == "slotting":
        Vc_lo, Vc_hi = Vc_lo * 0.4, Vc_hi * 0.7
    elif strat == "finishing":
        Vc_lo, Vc_hi = Vc_lo * 1.1, Vc_hi * 1.2
    if _out_of_band(calc["Vc"], Vc_lo, Vc_hi):
        issues.append(
            f"Vc {calc['Vc']:.0f} m/min outside [{Vc_lo:.0f},{Vc_hi:.0f}]±{TOL_PCT*100:.0f}%"
        ); ok = False

    # engagement ratios (skip for drilling, ballmills, face-milling ops)
    ttype = tool.get("type", "").lower()
    is_face_tool = "facemill" in ttype or "face mill" in ttype
    is_face_op   = any(
        k in step.get("step", "").lower() for k in ("face", "facing", "facemill", "face mill")
    )
    skip_ae = (
        strat == "drilling" or ttype == "ballmill" or is_face_tool or is_face_op
    )
     # face-milling: axial depth must be ≤ 2 mm (absolute) and ae/D already skipped
    if is_face_op and step.get("ap", 0) > 2.0:
        issues.append(f"ap {step['ap']} mm exceeds 2 mm limit for facing")
        ok = False

    if calc["D"] and not skip_ae:
        eng = cam.get_engagement_limits(strat)
        apR = step.get("ap", 0) / calc["D"]
        aeR = step.get("ae", 0) / calc["D"]
        if _out_of_band(apR, *eng["ap_d"]):
            issues.append(f"ap/D {apR:.2f} outside [{eng['ap_d'][0]:.2f},{eng['ap_d'][1]:.2f}]"); ok = False
        if not (aeR == 1.0 and strat == "drilling"):
            if _out_of_band(aeR, *eng["ae_d"]):
                issues.append(f"ae/D {aeR:.2f} outside [{eng['ae_d'][0]:.2f},{eng['ae_d'][1]:.2f}]"); ok = False

    # coating vs material class
    coating = tool.get("coating", "").lower()
    reqs = _COATING_REQ.get(mat_tag, [])
    if mat_tag == "N":
        if coating and coating != "uncoated":
            issues.append("tool coating not suitable for Al alloys"); ok = False
    else:
        if reqs and not any(r in coating for r in reqs):
            issues.append(f"tool coating '{tool.get('coating')}' not suitable for ISO-{mat_tag}"); ok = False

    # bore sanity (drilling only)
    if strat == "drilling" and "bore_diameter" in step:
        if calc["D"] > step["bore_diameter"]:
            issues.append("tool diameter exceeds bore diameter"); ok = False

    # ── 3) suggestions
    suggestions = suggest_corrections(step, machine, mat_tag, tool) if not ok else {}
    return ok, issues, suggestions


# ────────────────────────────────────────────────────────────────────────────
# Reporting helpers
# ────────────────────────────────────────────────────────────────────────────

def _flagged(label: str, val: str, faulty_keys: set[str]) -> str:
    mark = "⚠️" if label.lower() in faulty_keys else "✅"
    return f"{label}: {val} {mark}"


def summarize_step(step: Dict, ok: bool, issues: List[str]) -> str:
    status = "✅" if ok else "❌"
    calc = step.get("_calc", {})
    strat = step["strategy"]
    feed_label = "f_n" if strat == "drilling" else "f_z"
    feed_val = calc.get("fn" if strat == "drilling" else "fz", 0)

    line1 = (
        f"• Tool {step.get('tool_id')} (D={calc.get('D', '?')} mm, z={calc.get('z', '?')}) | "
        f"n={step.get('n', '?')} rpm | Vf={step.get('vf', '?')} mm/min | "
        f"Vc={calc.get('Vc', 0):.0f} m/min | {feed_label}={feed_val:.3f}"
    )
    line2 = (
        f"• ap={step.get('ap', '?')} mm | ae={step.get('ae', '?')} mm | strategy={strat}"
    )

    faulty = {w.lower().split()[0] for w in issues}
    out = [f"{status} {step['step']}"]
    out.append("   " + _flagged("tool", line1, faulty))
    out.append("   " + _flagged("cut", line2, faulty))
    for iss in issues:
        out.append(f"   - ⚠️ {iss}")
    return "\n".join(out)


def summarize_validation(plan_txt: str, machine: Dict, material: str) -> str:
    tag = cam.infer_material_tag(material)
    tools = machine.get("tool_library", [])
    blocks = []
    for st in parse_txt_plan(plan_txt):
        ok, issues, _ = validate_step(st, machine, tag, tools)
        st["_calc"] = _calc_values(st, _find_tool(st.get("tool_id"), tools))
        blocks.append(summarize_step(st, ok, issues))
    return "\n\n".join(blocks)

# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("plan")
    p.add_argument("machine")
    p.add_argument("material")
    a = p.parse_args()

    plan_txt = Path(a.plan).read_text(encoding="utf-8")
    mach_cfg = json.loads(Path(a.machine).read_text())
    print(summarize_validation(plan_txt, mach_cfg, a.material))
