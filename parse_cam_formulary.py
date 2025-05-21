# parse_cam_formulary.py
"""Parse CAM.txt and expose cutting‑parameter reference limits.

Dynamic extraction of:
• Cutting speed Vc ranges per ISO material class
• Feed per tooth fz ranges (rough / finish)
• Depth engagement ratios ap/D and ae/D for strategies (roughing, finishing, slotting)
• Cutting‑pressure constants kc0_4 and exponent x

Public helpers
--------------
infer_material_tag(text)  -> 'P' | 'M' | 'K' | 'N' | 'S' | 'H'
get_limits_for('N')       -> { 'Vc': (lo,hi), 'fz_rough': (lo,hi), 'fz_finish': (lo,hi), 'kc0_4': (lo,hi), 'x': (lo,hi) }
get_engagement_limits('finishing') -> { 'ap_d': (lo,hi), 'ae_d': (lo,hi) }
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Dict, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# 0 . Load formulary
# ─────────────────────────────────────────────────────────────────────────────
_CAM = Path("CAM.txt")
if not _CAM.exists():
    raise FileNotFoundError("CAM.txt not found – please place it in project root.")
_lines = [ln.rstrip() for ln in _CAM.read_text(encoding="utf-8").splitlines()]
_RANGE = re.compile(r"([\d\.]+)\s*[–-]\s*([\d\.]+)")  # e.g. 180 – 250


def _rng(s: str) -> Tuple[float, float]:
    m = _RANGE.search(s)
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)

# ─────────────────────────────────────────────────────────────────────────────
# 1 . Cutting‑speed Vc table (§1)
# ─────────────────────────────────────────────────────────────────────────────
_VC: Dict[str, Tuple[float, float]] = {}
sec = False
for ln in _lines:
    if ln.startswith("# 1. Cutting Speed"):
        sec = True
        continue
    if sec and ln.startswith("# ") and not ln.startswith("# 1"):
        break
    if sec and "|" in ln and ln.strip()[0] in "PMKNSH":
        iso = ln.strip()[0]
        _VC[iso] = _rng(ln)

# ─────────────────────────────────────────────────────────────────────────────
# 2 . Feed‑per‑tooth fz table (§2)
# ─────────────────────────────────────────────────────────────────────────────
_FZ_ROUGH: Dict[str, Tuple[float, float]] = {}
_FZ_FINISH: Dict[str, Tuple[float, float]] = {}
sec = False
for ln in _lines:
    if ln.startswith("# 2. Feed per Tooth"):
        sec = True
        continue
    if sec and ln.startswith("# ") and not ln.startswith("# 2"):
        break
    if sec and "|" in ln and ln.strip()[0] in "PMKNSH":
        iso = ln.strip()[0]
        if "Roughing" in ln:
            _FZ_ROUGH[iso] = _rng(ln)
        else:
            _FZ_FINISH[iso] = _rng(ln)

# ─────────────────────────────────────────────────────────────────────────────
# 3 . Engagement ratios table (§3)
# ─────────────────────────────────────────────────────────────────────────────
_ENG: Dict[str, Dict[str, Tuple[float, float]]] = {}
sec = False
for ln in _lines:
    if ln.startswith("# 3. Depths of Cut"):
        sec = True
        continue
    if sec and ln.startswith("# ") and not ln.startswith("# 3"):
        break
    if sec and "|" in ln and any(k in ln for k in ("Finishing", "Roughing", "Slotting")):
        cols = [c.strip() for c in ln.split("|")]
        key = cols[0].lower()
        _ENG[key] = {"ap_d": _rng(cols[1]), "ae_d": _rng(cols[2])}
# ensure keys exist to avoid KeyError
for k in ("roughing", "finishing", "slotting"):
    _ENG.setdefault(k, {"ap_d": (0, 0), "ae_d": (0, 0)})

# ─────────────────────────────────────────────────────────────────────────────
# 4 . Cutting‑pressure constants kc0_4 + exponent x (§9)
# ─────────────────────────────────────────────────────────────────────────────
_KC: Dict[str, Tuple[float, float]] = {}
_X: Dict[str, Tuple[float, float]] = {}
sec_kc = sec_x = False
for ln in _lines:
    if ln.startswith("# 9. Typical values"):
        sec_kc = True
        continue
    if sec_kc and "Typical exponent" in ln:
        sec_x = True
        continue
    if sec_kc and ln.startswith("# ") and not ln.startswith("# 9"):
        sec_kc = False
    if sec_x and ln.startswith("# ") and not ln.startswith("# 9"):
        sec_x = False
    if sec_kc and "->" in ln and ln.strip()[0] in "PMKNSH":
        iso = ln.strip()[0]
        _KC[iso] = _rng(ln)
    if sec_x and "->" in ln and ln.strip()[0] in "PMKNSH":
        iso = ln.strip()[0]
        _X[iso] = _rng(ln)

# ─────────────────────────────────────────────────────────────────────────────
# 5 . Public helpers
# ─────────────────────────────────────────────────────────────────────────────
_MAT = {
    "steel": "P", "carbon steel": "P", "mild steel": "P",
    "stainless": "M", "stainless steel": "M",
    "cast iron": "K", "grey iron": "K", "gray iron": "K",
    "aluminium": "N", "aluminum": "N",
    "titanium": "S", "superalloy": "S", "nickel alloy": "S",
    "hardened": "H", "hardened steel": "H", "tool steel": "H",
}


def infer_material_tag(text: str) -> str:
    txt = text.lower()
    for kw, tag in _MAT.items():
        if kw in txt:
            return tag
    return "P"


def get_limits_for(material: str | None) -> Dict:
    iso = (material or "P").upper()[0]
    return {
        "Vc": _VC.get(iso, (0, 0)),
        "fz_rough": _FZ_ROUGH.get(iso, (0, 0)),
        "fz_finish": _FZ_FINISH.get(iso, (0, 0)),
        "kc0_4": _KC.get(iso, (0, 0)),
        "x": _X.get(iso, (0, 0)),
    }


def get_engagement_limits(strategy: str = "roughing") -> Dict[str, Tuple[float, float]]:
    return _ENG.get(strategy.lower(), _ENG["roughing"])

# ─────────────────────────────────────────────────────────────────────────────
# 6 . Smoke test (optional)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mat_desc = input("Material description: ")
    tag = infer_material_tag(mat_desc)
    print("ISO tag:", tag)
    print("Limits:", get_limits_for(tag))
    print("Finishing engagement:", get_engagement_limits("finishing"))
    print("Roughing engagement:", get_engagement_limits("roughing"))
    print("Slotting engagement:", get_engagement_limits("slotting"))
    print("Cutting pressure:", get_limits_for(tag)["kc0_4"])
    print("Exponent:", get_limits_for(tag)["x"])
    print("Cutting speed:", get_limits_for(tag)["Vc"])
    print("Feed per tooth (rough):", get_limits_for(tag)["fz_rough"])
    print("Feed per tooth (finish):", get_limits_for(tag)["fz_finish"])
    print("Done.")