from __future__ import annotations
import json, math, re
from pathlib import Path
from typing import Dict, List, Tuple

import parse_cam_formulary as cam

_STEP_HDR = re.compile(
    r"""
    ^\s*                      # optional leading spaces
    (?:\#+\s*)?                # optional markdown header like ### or ##
    (\d+)                     # step number (captured)
    [\.\)]\s*                 # dot or parenthesis like "3." or "3)"
    (?:\*\*|__)?              # optional opening bold (** or __)
    (.+?)                     # the title (non-greedy)
    (?:\*\*|__)?              # optional closing bold
    \s*$                     # end of line
    """,
    re.MULTILINE | re.VERBOSE
)

_NUM = re.compile(r"([\d\.]+)")

def _strategy(name: str) -> str:
    name = name.lower()
    if any(k in name for k in ("finish", "swarf")): return "finishing"
    if "slot" in name: return "slotting"
    return "roughing"

def parse_txt_plan(text: str) -> List[Dict]:
    steps: List[Dict] = []
    headers = list(_STEP_HDR.finditer(text))
    for i, h in enumerate(headers):
        blk  = text[h.end(): headers[i + 1].start() if i + 1 < len(headers) else len(text)]
        step = {"step": h.group(1).strip(), "strategy": _strategy(h.group(1))}
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
        print(f"[DEBUG] Parsed {len(steps)} steps.")

    return steps


def _find_tool(tid: int, tools: List[Dict]) -> Dict:
    return next((t for t in tools if t.get("id") == tid), {})

def _calc_values(step: Dict, tool: Dict) -> Dict[str, float]:
    D  = tool.get("dia", step.get("tool_dia", 0)) or 0
    z  = tool.get("flutes", 1)
    n  = step.get("n", 0)
    vf = step.get("vf", 0)
    Vc = math.pi * D * n / 1000 if D else 0
    fz = vf / (n * z) if n and z else 0
    return {"D": D, "z": z, "Vc": Vc, "fz": fz}

def _loc_to_mm(loc_val, tool_dia: float) -> float:
    if isinstance(loc_val, (int, float)): return float(loc_val)
    if not isinstance(loc_val, str): return math.inf
    s, m = loc_val.lower(), _NUM.search(loc_val)
    if not m: return math.inf
    num = float(m.group(1))
    return num * tool_dia if "x" in s and "d" in s else num

def validate_step(step: Dict, machine: Dict, mat_tag: str, tools: List[Dict]) -> Tuple[bool, List[str]]:
    tool  = _find_tool(step.get("tool_id"), tools)
    calc  = _calc_values(step, tool)
    loc_mm= _loc_to_mm(tool.get("loc", math.inf), calc["D"])

    issues, ok = [], True
    if step.get("n", 0)  > machine.get("max_spindle_rpm", 9e9):
        issues.append("rpm > machine limit"); ok=False
    if step.get("vf", 0) > machine.get("max_feed_rate", 9e9):
        issues.append("feed > machine limit"); ok=False
    if step.get("ap", 0) > loc_mm:
        issues.append("ap exceeds tool LOC"); ok=False
    # material limits
    lim   = cam.get_limits_for(mat_tag)
    strat = step["strategy"]
    Vc_lo, Vc_hi = lim["Vc"]
    fz_lo, fz_hi = lim["fz_finish"] if strat == "finishing" else lim["fz_rough"]

    if calc["Vc"] < Vc_lo or calc["Vc"] > Vc_hi:
        issues.append(f"Vc {calc['Vc']:.0f} m/min outside [{Vc_lo:.1f},{Vc_hi:.1f}] for ISO {mat_tag}")
        ok = False

    if fz_lo and (calc["fz"] < fz_lo or calc["fz"] > fz_hi):
        issues.append(f"f_z {calc['fz']:.3f} mm/tooth outside [{fz_lo:.2f},{fz_hi:.2f}]")
        ok = False

    # engagement ratios
    eng = cam.get_engagement_limits(strat)
    if calc["D"]:
        apR = step.get("ap", 0) / calc["D"]
        aeR = step.get("ae", 0) / calc["D"]
        ap_lo, ap_hi = eng["ap_d"]
        ae_lo, ae_hi = eng["ae_d"]
        if not (ap_lo <= apR <= ap_hi):
            issues.append(f"ap/D {apR:.2f} outside [{ap_lo:.1f},{ap_hi:.1f}]")
        if not (ae_lo <= aeR <= ae_hi):
            issues.append(f"ae/D {aeR:.2f} outside [{ae_lo:.1f},{ae_hi:.1f}]")

    return ok, issues

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
        f"f_z={calc.get('fz', 0):.3f}"
    )
    line2 = (
        f"• ap={step.get('ap', '?')} mm | "
        f"ae={step.get('ae', '?')} mm | "
        f"strategy={step['strategy']}"
    )
    out = [f"{status} {step['step']}"]
    out.append("   " + _flagged("tool", line1, faulty))
    out.append("   " + _flagged("ap",   line2, faulty))
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
