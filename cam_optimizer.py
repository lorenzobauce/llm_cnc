# cam_optimizer.py
"""Interactive CAM-plan optimiser with infinite refinement loop.

At each round:
  ✓ Prints full plan
  ✓ Runs validator with ✅ / ⚠️ per parameter
  ✓ Asks user whether to regenerate
  ✓ Stops only when user says NO
"""

from __future__ import annotations
import json
import textwrap
from pathlib import Path
from typing import List, Dict, Tuple
import affordance_validator as av
from affordance_validator import summarize_validation
from prompt_utils import build_process_prompt
from prompt_utils import _fmt_tool_list
from llm_client import client as _openai
from llm_client import call_llm_with_system
from rich.progress import Progress, SpinnerColumn, TextColumn

# ─────────────────────────────────────────────────────────────────────────────
MODEL = "gpt-4o"
# ─────────────────────────────────────────────────────────────────────────────

def _read(p: str) -> str:
    return Path(p).read_text(encoding="utf-8")


def optimise_plan(
                  description: str,
                  plan_path: str,
                  machine_path: str,
                  material_desc: str,
                  image_url: str | None = None,
                  context_block: str = "") -> str:

    """
    Infinite refinement loop until user exits.
    Returns final plan string.
    """
    plan_txt = _read(plan_path)
    machine = json.loads(_read(machine_path))    
    tools    = machine.get("tool_library", [])
    tag      = av.cam.infer_material_tag(material_desc)
    
    tool_block = _fmt_tool_list(machine.get("tool_library", []))

    machine_block = textwrap.dedent(f"""
    ### CNC Machine Specifications
    Name: {machine.get('name','')}
    Axes: {machine.get('axes','')}
    Max X axis stroke: {machine.get('max_X_axis_stroke','?')} mm
    Max Y axis stroke: {machine.get('max_Y_axis_stroke','?')} mm
    Max Z axis stroke: {machine.get('max_Z_axis_stroke','?')} mm
    Min A axis swivel angle: {machine.get('A_axis_min_swivel_angle','?')} ° (if applicable)
    Max A axis swivel angle: {machine.get('A_axis_max_swivel_angle','?')} ° (if applicable)
    Min B axis swivel angle: {machine.get('B_axis_min_swivel_angle','?')} ° (if applicable)
    Max B axis swivel angle: {machine.get('B_axis_max_swivel_angle','?')} ° (if applicable)
    Raneg C axis swivel angle: {machine.get('C_axis_swivel_angle','?')} ° (if applicable)
    Max workpiece diameter: {machine.get('max_workpiece_diameter','?')} mm
    Max workpiece height: {machine.get('max_workpiece_height','?')} mm
    Max workpiece weight: {machine.get('max_workpiece_weight','?')} kg
    Max spindle RPM: {machine.get('max_spindle_rpm','?')} rpm
    Max feed rate: {machine.get('max_feed_rate','?')} mm/min
    Max spindle power: {machine.get('spindle_power', '?')} kW
    Max spindle torque: {machine.get('spindle_torque', '?')} N·m
    Tool change type: {machine.get('tool_change_type','?')}
    Storage capacity {machine.get('tool_storage_capacity','?')} tools

    #### Tool Library
    {tool_block}
    """).strip()

# ─────────────────────────────────────────────────────────────────────────────

    while True:
        print("\n--- CNC PROCESS PLAN ---\n")
        print(plan_txt)

        print("\n--- AFFORDANCE VALIDATOR REPORT ---\n")
        print(summarize_validation(plan_txt, machine, material_desc))

        answer = input("\n❓ Would you like to regenerate with corrections? [y/N]: ").strip().lower()
        if answer != "y":
            break

        # parse steps + collect issues
        steps = av.parse_txt_plan(plan_txt)
        issues, fixes = _collect_issues(steps, machine, tag, tools)

        # build prompt
        prompt = textwrap.dedent(f"""
            ## Below is the current process plan for the part imported as image with detected issues.
            **Please regenerate the entire process plan, keeping the same numbering, headings, and all the fields that are existing.**
            **Substitute only the corrected parameters (n, Vf, ap, ae) that are suggested.**
                                 
            ## Part description / user goal
            {description}
            
            ## Process plan
            {plan_txt}

            ## Detected issues
            {chr(10).join(issues)}

            ## Suggested fixes
            {chr(10).join(fixes)}

            ## Contextual information
            {context_block}

            {machine_block}

            ## Tool Library
            {tool_block}
   
        """)


        # call LLM
        with Progress(SpinnerColumn(), TextColumn("Regenerating…")) as bar:
            t = bar.add_task("llm"); bar.start_task(t)
            if image_url:
                plan_txt = call_llm_with_system(prompt, image_url,
                                                system_message="You are an expert mechanical CAM engineer who assist the user developing the complete manufacturing process.",
                                                model=MODEL)
            else:
                res = _openai.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}]
                )
                plan_txt = res.choices[0].message.content
            bar.stop_task(t)

    return plan_txt


def _collect_issues(steps: List[Dict],
                    machine: Dict,
                    tag: str,
                    tools: List[Dict]) -> Tuple[List[str], List[str]]:
    """
    Returns:
        - List of issue strings (for the prompt)
        - (Unused) List of suggested corrections (not shown to user)
    """
    issues_out, fix_out = [], []
    sugg_fn = getattr(av, "suggest_corrections", None)

    for st in steps:
        res = av.validate_step(st, machine, tag, tools)
        ok  = res[0]
        err = res[1]
        sug = res[2] if len(res) == 3 else {}
        if not ok and not sug and callable(sugg_fn):
            tool_obj = next((t for t in tools if t.get("id") == st.get("tool_id")), {})
            sug = sugg_fn(st, machine, tag, tool_obj)
        if not ok:
            issues_out.append(f"Step “{st['step']}”: " + ", ".join(err))
            if sug:
                fix_out.append(
                    f"{st['step']} → n={sug.get('n','?')} | Vf={sug.get('vf','?')} | "
                    f"ap={sug.get('ap','?')} | ae={sug.get('ae','?')}"
                )
    return issues_out, fix_out


if __name__ == "__main__":
    import argparse
    cli = argparse.ArgumentParser(description="Interactive CAM Plan Optimiser")
    cli.add_argument("plan")
    cli.add_argument("machine")
    cli.add_argument("material")
    cli.add_argument("--image")
    args = cli.parse_args()

    final = optimise_plan(args.plan, args.machine, args.material, args.image)
    print("\n--- FINAL PLAN ---\n")
    print(final)
