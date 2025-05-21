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
from pathlib import Path
from typing import List, Dict, Tuple

# --- Validator & formatting
import affordance_validator as av
from affordance_validator import summarize_validation
from prompt_utils import build_process_prompt

# --- LLM
from llm_client import client as _openai
from llm_client import call_llm_with_system

# --- Progress bar
from rich.progress import Progress, SpinnerColumn, TextColumn


MODEL = "gpt-4o"


def _read(p: str) -> str:
    return Path(p).read_text(encoding="utf-8")


def optimise_plan(plan_path: str,
                  machine_path: str,
                  material_desc: str,
                  image_url: str | None = None,
                  description: str = "",
                  context_block: str = "") -> str:

    """
    Infinite refinement loop until user exits.
    Returns final plan string.
    """
    plan_txt = _read(plan_path)
    machine  = json.loads(_read(machine_path))
    tools    = machine.get("tool_library", [])
    tag      = av.cam.infer_material_tag(material_desc)

    while True:
        print("\n--- CNC PROCESS PLAN ---\n")
        print(plan_txt)

        print("\n--- AFFORDANCE VALIDATOR REPORT ---\n")
        print(summarize_validation(plan_txt, machine, material_desc))

        answer = input("\nWould you like to regenerate with corrections? [y/N]: ").strip().lower()
        if answer != "y":
            break

        # parse steps + collect issues
        steps = av.parse_txt_plan(plan_txt)
        issues, fixes = _collect_issues(steps, machine, tag, tools)

        # build prompt
        prompt = (
            build_process_prompt(description, machine)
            + "\n\n### Technical context (from CAM formulary)\n"
            + context_block
            + "\n\n"
            + "## Tentative process plan\n {plan_txt} \n\n"
            + "## Detected issues\n" + "\n".join(issues) + "\n\n"
            + "## Mandatory parameter fixes\n" + "\n".join(fixes) + "\n\n"
            + "Regenerate the **entire process plan**, keeping the same numbering and headings, but apply only the corrected parameters."
        )


        # call LLM
        with Progress(SpinnerColumn(), TextColumn("Regenerating…")) as bar:
            t = bar.add_task("llm"); bar.start_task(t)
            if image_url:
                plan_txt = call_llm_with_system(prompt, image_url,
                                                system_message="You are an expert CAM engineer.",
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
