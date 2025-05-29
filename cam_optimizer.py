# cam_optimizer.py

from __future__ import annotations
import json
import textwrap
from pathlib import Path
from typing import List, Dict, Tuple
import affordance_validator as av
from affordance_validator import summarize_validation
from prompt_utils import _fmt_tool_list
from llm_client import client as _openai
from llm_client import call_llm_with_system
from rich.progress import Progress, SpinnerColumn, TextColumn



# ─────────────────────────────────────────────────────────────────────────────
MODEL = "gpt-4o" 
#MODEL = "gpt-4o-mini"
# ─────────────────────────────────────────────────────────────────────────────

def _read(p: str) -> str:
    return Path(p).read_text(encoding="utf-8")



# ─────────────────────────────────────────────────────────────────────────────
# Public entry‑point
# ─────────────────────────────────────────────────────────────────────────────

def optimise_plan(
                  description: str,
                  plan_path: str,
                  machine_path: str,
                  material_desc: str,
                  image_url: str | None = None,
                  context_block: str = "") -> str:

    """
    Infinite refinement loop until the operator exits.
    Returns the *final* plan string that satisfied the user.
    """
    plan_txt = _read(plan_path)
    machine = json.loads(_read(machine_path))    
    tools    = machine.get("tool_library", [])
    tag      = av.cam.infer_material_tag(material_desc)
    
    tool_block = _fmt_tool_list(machine.get("tool_library", []))

    machine_block = textwrap.dedent(f"""
    Name: {machine.get('name','')}
    Axes: {machine.get('axes','')}
    Max X axis stroke: {machine.get('max_X_axis_stroke','?')} mm
    Max Y axis stroke: {machine.get('max_Y_axis_stroke','?')} mm
    Max Z axis stroke: {machine.get('max_Z_axis_stroke','?')} mm
    Max spindle RPM: {machine.get('max_spindle_rpm','?')} rpm
    Max feed rate: {machine.get('max_feed_rate','?')} mm/min
    Max spindle power: {machine.get('spindle_power', '?')} kW
    Max spindle torque: {machine.get('spindle_torque', '?')} N·m

    #### Tool Library
    {tool_block}
    """).strip()

    _FORMULA_BLOCK = """
    Vc  = (pi * D * n) / 1000          # Cutting speed  [m/min]
    f_z = Vf / (n * z)                 # Feed per tooth [mm/tooth]
    apD = ap / D                       # Axial depth ratio
    aeD = ae / D                       # Radial engagement ratio
    """


# ─────────────────────────────────────────────────────────────────────────────

    while True:
        print("\n--- CNC PROCESS PLAN ---\n")
        print(plan_txt)

        print("\n--- AFFORDANCE VALIDATOR REPORT ---\n")
        print(summarize_validation(plan_txt, machine, material_desc))

        answer = input("\n❓ Would you like to regenerate the process with corrections? [y/N]: ").strip().lower()
        if answer != "y":
            break

        # ════════════════════════════════════════════════════════════════
        # Gather issues + numeric fixes
        # ════════════════════════════════════════════════════════════════
        steps = av.parse_txt_plan(plan_txt)
        issues, fixes, tool_advise = _collect_issues(steps, machine, tag, tools)

        # Build LLM prompt ------------------------------------------------        
        prompt = textwrap.dedent(f"""\
        ## Below is the current process plan for the part imported as image with detected issues.
        **Please regenerate the entire process plan, keeping the same numbering, headings, and all the fields that are existing.**
        **Substitute only the corrected parameters (n, Vf, ap, ae) that are suggested.**
                        
        ## Part description / user goal
        {description}

        ## Current manufacturing plan (with detected issues below)
        {plan_txt}

        ## Detected issues
        {chr(10).join(issues)}

        ## Suggested process parameter fixes
        ** Numeric parameters listed below are provided by reference, but it is *better* that you compute the parameters by yourself, using the formulas below. 
        Do *not* re-introduce ranges; change only the specified fields (n, Vf, ap, ae).**
        {chr(10).join(fixes)}

        ## Tooling advice
        {chr(10).join(tool_advise) if tool_advise else '- None -'}

        ## Formula block
        {_FORMULA_BLOCK}

        ## Contextual information
        {context_block}

        ### CNC Machine Specifications
        {machine_block}
        """)


        # DEBUG: print the prompt to LLM
        # print("\n--- DEBUG: PROMPT TO LLM ---\n")
        # print(prompt)


        # Call LLM ---------------------------------------------------------
        with Progress(SpinnerColumn(), TextColumn("Regenerating…")) as bar:
            t = bar.add_task("llm"); bar.start_task(t)
            if image_url:
                plan_txt = call_llm_with_system(prompt, image_url,
                                                system_message="You are an expert mechanical CAM engineer assisting the user developing the complete manufacturing process.",
                                                model=MODEL)
            else:
                res = _openai.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}]
                )
                plan_txt = res.choices[0].message.content
            if "i'm sorry" in plan_txt.lower() or "i am sorry" in plan_txt.lower():
                from utils import save_llm_io
                save_llm_io(prompt, plan_txt)     
            bar.stop_task(t)

    return plan_txt



# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _collect_issues(steps: List[Dict],
                    machine: Dict,
                    tag: str,
                    tools: List[Dict]) -> Tuple[List[str], List[str]]:
    """
    Returns:
        - List of issue strings
        - List of suggested corrections
        - List of tool advice (if any)
    """
    issues_out, fix_out, tool_adv = [], [], []

    sugg_fn = getattr(av, "suggest_corrections", None)

    for st in steps:
        res = av.validate_step(st, machine, tag, tools)
        ok  = res[0]
        err = res[1]
        sug = res[2] if len(res) == 3 else {}

        if ok:
            continue

        # 1) human‑readable issue list
        issues_out.append(f"Step “{st['step']}”: " + ", ".join(err))

        # 2) numeric overrides for the LLM
        if sug:
            line = (
                f"{st['step']} → tool_id={sug.get('tool_id', st.get('tool_id', '?'))} | "
                f"n={sug['n']} | Vf={sug['vf']}"
            )
            if 'ap' in sug:       # milling cases
                line += f" | ap={sug['ap']} | ae={sug['ae']}"
            fix_out.append(line)


        # 3) ask for a different tool when coating / LOC / Ø is invalid
        warn_tool = [w for w in err if "tool coating" in w.lower()
                                     or "exceeds tool loc" in w.lower()
                                     or "tool diameter exceeds" in w.lower()]
        if warn_tool:
            tool_adv.append(
                f"Step “{st['step']}”: current tool unsuitable; "
                "use another tool available in the library, or keep the same tool in the process "
                "but suggest a suitable tool with different diameter and/or coating *ONLY BELOW THE FINAL NOTES* section."
            )

    return issues_out, fix_out, tool_adv



# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    cli = argparse.ArgumentParser(description="Interactive CAM Plan Optimiser")
    cli.add_argument("plan")
    cli.add_argument("machine")
    cli.add_argument("material")
    cli.add_argument("--image")
    args = cli.parse_args()

    final = optimise_plan(
        description="",  # interactive version can pass an empty description
        plan_path=args.plan,
        machine_path=args.machine,
        material_desc=args.material,
        image_url=args.image,
    )    
    
    print("\n--- FINAL PLAN ---\n")
    print(final)
