# dimension_extractor.py
import json, re
from typing import Dict
from llm_client import call_llm_with_system

# ---- LLM prompt that works for pulley drawings ----------
_DIM_PROMPT = (
    "Read the image and extract all numeric dimensions from this technical drawing. "
    "Return ONLY valid JSON with keys: "
    "outer_diameter_mm, pitch_diameter_mm, bore_diameter_mm, total_width_mm, "
    "belt_width_mm, tooth_pitch_mm, num_teeth. "
    "All numbers in millimetres. Omit a key if not visible. "
    "If the image is NOT a technical drawing, return an empty JSON object."
)

_REQUIRED = {
    "outer_diameter_mm" : "Outer diameter",
    "pitch_diameter_mm" : "Pitch diameter",
    "bore_diameter_mm"  : "Bore (shaft) diameter",
    "total_width_mm"    : "Total width",
    "belt_width_mm"     : "Belt groove width",
    "tooth_pitch_mm"    : "Tooth pitch",
    "num_teeth"         : "Number of teeth"
}

def _ask_missing(llm_geo: Dict) -> Dict:
    """Prompt the user for any geometry values the LLM could not read."""
    filled = llm_geo.copy()
    for k, label in _REQUIRED.items():
        v = str(filled.get(k, "")).lower()
        if v in {"", "none", "null", "unknown"}:
            while True:
                try:
                    filled[k] = float(input(f"❓  {label} not detected – enter value [mm]: "))
                    break
                except ValueError:
                    print("⚠  Please enter a numeric value.")
    return filled


def extract_geometry(image_data_url: str) -> Dict:
    """
    Call the vision model, parse its JSON, then interactively
    ask the user for any missing dimensions.
    """
    llm_raw = call_llm_with_system(
        _DIM_PROMPT,
        image_data_url,
        system_message="You are a mechanical engineer who reads techical drawings."
    )
    match = re.search(r"\{.*?\}", llm_raw, re.S)
    llm_geo = json.loads(match.group() if match else "{}")
    return _ask_missing(llm_geo)


def summary_text(geo: Dict) -> str:
    """Nicely formatted multiline summary for the CAM prompt."""
    return (
        f"Pulley outer diameter: {geo.get('outer_diameter_mm', '?')} mm\n"
        f"Pitch diameter:       {geo.get('pitch_diameter_mm', '?')} mm\n"
        f"Bore diameter:        {geo.get('bore_diameter_mm',  '?')} mm\n"
        f"Total width:          {geo.get('total_width_mm',    '?')} mm\n"
        f"Belt width:           {geo.get('belt_width_mm',     '?')} mm\n"
        f"Tooth pitch:          {geo.get('tooth_pitch_mm',    '?')} mm\n"
        f"Number of teeth:      {geo.get('num_teeth',         '?')}"
    )
