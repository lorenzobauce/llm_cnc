# prompt_utils.py
"""Prompt builder for vision RAG CAM assistant.
Returns a rich system/user prompt that:
- Describes the part & user intent
- Injects all relevant machine capabilities
- Lists full tool library with critical data (diameter, flutes, coating, LOC…) 
- Asks the LLM to CHECK manufacturability (envelope, weight, reach, power/torque, axis limits…)
"""
from typing import Dict, List
import textwrap


def _fmt_tool_list(tools: List[Dict]) -> str:
    """Pretty format tool library as markdown table."""
    if not tools:
        return "(No tools found)"
    header = "| ID | Type | D (mm) | Flutes | Coating | LOC (mm) | Notes |"
    rows   = ["|---|---|---|---|---|---|---|"]
    for t in tools:
        rows.append(
            f"| {t.get('id')} | {t.get('type')} | {t.get('dia')} | {t.get('flutes','?')} | "
            f"{t.get('coating','-')} | {t.get('loc', '?')} | {t.get('notes','')} |")
    return "\n".join([header, *rows])



def build_process_prompt(description: str, machine: Dict) -> str:
    """Return a detailed prompt string for CAM reasoning."""

    tool_block = _fmt_tool_list(machine.get("tool_library", []))

    machine_block = textwrap.dedent(f"""
    ### CNC Machine Specifications
    Name: {machine.get('name','')}
    Axes: {machine.get('axes','')}
    Max X axis stroke: {machine.get('max_X_axis_stroke','?')} mm
    Max Y axis stroke: {machine.get('max_Y_axis_stroke','?')} mm
    Max Z axis stroke: {machine.get('max_Z_axis_stroke','?')} mm
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

    manufacturability = textwrap.dedent("""
    ### Manufacturability checks (MUST perform before outputting plan)
    1. Envelope: Confirm the part bounding box fits within machine XYZ travel (include any rotary table tilt).
    2. Weight: Ensure workpiece weight ≤ machine limit.
    3. Tool reach: Compare pocket depth / wall height vs available LOC; suggest alternative tool if too short.
    4. Spindle capability: Ensure required torque / power for roughing ops ≤ machine limits.
    5. Axis limits & collisions: Consider fixture height and rotary axes when planning 5 axis moves.
    6. Material compatibility: Apply appropriate cutting data from formulary for specified material.
    If ANY check fails, explain the issue and propose mitigations (different setup, smaller cutter, etc.).
    """).strip()

    prompt = textwrap.dedent(f"""
    You are an expert CAM engineer.

    ## Part description / user goal
    {description}
    {machine_block}
    {manufacturability}

    ### Output requirements
    • Start with a short consideration confirming manufacturability with the provided machine and tools.
    • If YES: provide step-by-step process plan with sections.
    • For each step include: Tool ID, operation type, spindle speed (n), feedrate (vf), depth/pass (ap), side engagement (ae), coolant on/off, notes.
    • If NO: detail each blocking issue and suggest concrete actions.
    • Write all equations and numbers in plain text using ASCII (e.g. n = 1000 * Vc / (pi * D)).
    """)

    return prompt.strip()

# Use Markdown formatting and LaTeX for any equations (e.g. `n = \\frac{{1000 \\cdot V_c}}{{\\pi \\cdot D}}`).