# main.py – Vision-RAG + iterative validator loop
from __future__ import annotations
import os, json, base64, tempfile, shutil, inquirer, textwrap
from pathlib import Path
from tkinter import Tk, filedialog
from rich.progress import Progress, SpinnerColumn, TextColumn

from prompt_utils      import build_process_prompt
from llm_client        import call_llm, call_llm_with_system
from retrieve_context  import get_relevant_context
from dimension_extractor import extract_geometry, summary_text

import affordance_validator as av
from cam_optimizer import optimise_plan

# ─────────────────────────────────────────────────────────────────────────────
# UI helpers
# ─────────────────────────────────────────────────────────────────────────────
def _choose_file(msg: str, folder: str, exts: tuple[str, ...]) -> str:
    files = [f for f in os.listdir(folder) if f.lower().endswith(exts)]
    sel   = inquirer.prompt([inquirer.List("f", message=msg, choices=files)])
    return Path(folder, sel["f"]).as_posix()

def ask_save_location() -> str | None:
    root = Tk(); root.withdraw()
    return filedialog.asksaveasfilename(defaultextension=".txt",
                                        filetypes=[("Text files","*.txt")])

# ─────────────────────────────────────────────────────────────────────────────
# 1. Pick drawing & encode
# ─────────────────────────────────────────────────────────────────────────────
image_path  = _choose_file("Select drawing", "dataset", (".png", ".jpg", ".jpeg"))
img_b64     = base64.b64encode(Path(image_path).read_bytes()).decode()
image_data  = f"data:image/jpeg;base64,{img_b64}"

# ─────────────────────────────────────────────────────────────────────────────
# 2. Auto-geometry + user input
# ─────────────────────────────────────────────────────────────────────────────
geo = extract_geometry(image_data)
print("\n--- Geometry ---\n" + summary_text(geo) + "\n")

user_prompt   = input("❓ Describe what you want to machine / ask CAM assistant: ")
material_desc = input("❓ Material description: ")
text_desc     = textwrap.dedent(f"""
                                {user_prompt}
                                Material description: {material_desc}
                                {summary_text(geo)}
                                """)

# ─────────────────────────────────────────────────────────────────────────────
# 3. Machine selection
# ─────────────────────────────────────────────────────────────────────────────
machine_file = _choose_file("Select machine", "machines", (".json",))
machine_spec = json.loads(Path(machine_file).read_text())

# ─────────────────────────────────────────────────────────────────────────────
# 4. Build RAG prompt & get initial plan
# ─────────────────────────────────────────────────────────────────────────────
ctx_chunks = get_relevant_context(text_desc, k=8)
rag_prompt = (
    build_process_prompt(text_desc, machine_spec)
    + "\n\n### Technical context (from CAM formulary)\n"
    + "\n\n".join(ctx_chunks)
)

print("\nCalling GPT-4o for initial plan …")
with Progress(SpinnerColumn(), TextColumn("Generating…")) as bar:
    t = bar.add_task("llm"); bar.start_task(t)
    init_plan = call_llm_with_system(rag_prompt,
                                     image_data,
                                     system_message="You are an expert mechanical CAM engineer who assist the user developing the complete manufacturing process.")
    bar.stop_task(t)

# ─────────────────────────────────────────────────────────────────────────────
# 5. Interactive optimisation loop (calls cam_optimizer)
# ─────────────────────────────────────────────────────────────────────────────
tmp_dir  = tempfile.mkdtemp(prefix="cam_iter_")
tmp_file = Path(tmp_dir, "plan_0.txt"); tmp_file.write_text(init_plan, encoding="utf-8")
context_block = "\n\n".join(ctx_chunks)      
tmp_file.write_text(init_plan, encoding="utf-8")

final_plan = optimise_plan(
    tmp_file.as_posix(),
    machine_file,
    material_desc,
    image_url=None,
    description=text_desc,
    context_block=context_block
)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Show final plan + validator, then ask to save
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- FINAL CNC PROCESS PLAN ---\n")
print(final_plan)

print("\n--- FINAL VALIDATOR REPORT ---\n")
print(av.summarize_validation(final_plan, machine_spec, material_desc))

save = ask_save_location()
if save:
    Path(save).write_text(final_plan, encoding="utf-8")
    print("\n\n✅ Saved to:", save)
else:
    print("\n\n⚠️ [Skipped] File was not saved.")

shutil.rmtree(tmp_dir)
