# utils.py
from datetime import datetime
from pathlib import Path

def save_llm_io(prompt: str, response: str, tag: str = "refusal") -> None:
    """Salva prompt e risposta solo per debug; nessuna stampa a video."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    ts   = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file = log_dir / f"{ts}_{tag}.txt"

    with file.open("w", encoding="utf-8") as f:
        f.write("### PROMPT ###\n")
        f.write(prompt)
        f.write("\n\n### RESPONSE ###\n")
        f.write(response)
