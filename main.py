# main.py
# Custom RAG + Vision LLM pipeline tailored for CAM engineering.
import os
import json
import base64
import inquirer
from tkinter import Tk, filedialog
from prompt_utils import build_process_prompt
from llm_client import call_llm
from retrieve_context import get_relevant_context
from dimension_extractor import extract_geometry, summary_text


# === Choose the component from the images in the dir ===
def choose_image_file(directory: str = '.') -> str:
    image_files = [f for f in os.listdir(directory) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    if not image_files:
        raise FileNotFoundError("No image files (.jpg/.png) found in this directory.")
    questions = [
        inquirer.List(
            'image',
            message="Select an image file:",
            choices=image_files
        )
    ]
    answers = inquirer.prompt(questions)
    return os.path.join(directory, answers['image'])

# === Choose the machine tool from the current available in the dir ===
def choose_machine_file(directory: str = '.') -> str:
    json_files = [f for f in os.listdir(directory) if f.lower().endswith('.json')]
    if not json_files:
        raise FileNotFoundError("No machine spec files (.json) found in this directory.")
    questions = [
        inquirer.List(
            'machine',
            message="Select a machine spec file:",
            choices=json_files
        )
    ]
    answers = inquirer.prompt(questions)
    return os.path.join(directory, answers['machine'])

# === Ask user where to save the file ===
def ask_save_location():
    root = Tk()
    root.withdraw()
    file_path = filedialog.asksaveasfilename(
        defaultextension=".txt",
        filetypes=[("Text files", "*.txt")],
        title="Save process plan"
    )
    return file_path


# =========================== MAIN PROGRAM =========================== #

# STEP 1 – choose image
image_path = choose_image_file(directory="dataset")
with open(image_path, "rb") as f:
    img_base64 = base64.b64encode(f.read()).decode()
image_data_url = f"data:image/jpeg;base64,{img_base64}"


# STEP 2 – automatic + interactive geometry extraction
geometry = extract_geometry(image_data_url)
geometry_summary = summary_text(geometry)
print ("\n--- Extracted Geometry ---\n")
print(geometry_summary)
user_query = input("\nDescribe what you want to machine / ask the CAM assistant: ")
text_description = user_query.strip() + "\n\n" + geometry_summary


# STEP 3 – choose machine spec
machine_file = choose_machine_file(directory="machines")
with open(machine_file) as f:
    machine_spec = json.load(f)


# STEP 4 – build RAG prompt + call LLM
context_chunks = get_relevant_context(text_description, k=6)
print("\n=== Context chunks ===\n")
for i, chunk in enumerate(context_chunks, 1):
    print(f"[{i}] {chunk}\n")

wait = input("Press Enter to continue...")

context_block  = "\n\n".join(context_chunks)
prompt = (
    build_process_prompt(text_description, machine_spec)
    + "\n\n### Technical context (from CAM formulary)\n"
    + context_block
)
response = call_llm(prompt, image_data_url)


# STEP 5 – show result
print("\n--- CNC Process Plan ---\n")
print(response)


# STEP 6 – ask where to save
save_path = ask_save_location()
if save_path:
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(response)
    print(f"\nProcess plan saved to: {save_path}")
else:
    print("\n[Skipped] File was not saved.")