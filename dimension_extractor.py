import easyocr
import cv2
import numpy as np
import re
from typing import Dict, List

def extract_dimensions_from_image(image_path: str) -> Dict:
    """
    Extract numeric dimensions from a technical drawing image.
    Attempts to identify feature-related dimensions using OCR + heuristics.
    """
    reader = easyocr.Reader(['en'], gpu=True)
    image = cv2.imread(image_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Run OCR
    results = reader.readtext(gray, detail=1)

    dimension_values: List[float] = []
    hole_diameters: List[float] = []
    part_lengths: List[float] = []
    pocket_sizes: List[float] = []

    for bbox, text, conf in results:
        if conf < 0.4:
            continue  # skip low-confidence

        clean = text.replace(',', '.').replace('Ø', '').strip()
        match = re.match(r"^\d+(\.\d+)?$", clean)

        if match:
            val = float(clean)
            dimension_values.append(val)

            # Heuristics
            if 'Ø' in text or 'D=' in text:
                hole_diameters.append(val)
            elif val > 100:
                part_lengths.append(val)
            elif 10 < val < 100:
                pocket_sizes.append(val)

    # Deduplicate and sort
    result = {
        "all_detected": sorted(set(dimension_values)),
        "max_detected": max(dimension_values) if dimension_values else None,
        "part_lengths": sorted(set(part_lengths), reverse=True),
        "hole_diameters": sorted(set(hole_diameters), reverse=True),
        "pocket_sizes": sorted(set(pocket_sizes), reverse=True)
    }
    return result

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python extract_dimensions.py <image_path>")
        exit()

    image_path = sys.argv[1]
    dims = extract_dimensions_from_image(image_path)
    print("\nExtracted dimensions:")
    for k, v in dims.items():
        print(f"{k}: {v}")
