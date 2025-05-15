# main.py
# Custom RAG + Vision LLM pipeline tailored for CAM engineering.
import os
import json
import base64
import inquirer
from prompt_utils import build_process_prompt
from llm_client import call_llm
from retrieve_context import get_relevant_context
from tkinter import Tk, filedialog
# from dimension_extractor import extract_dimensions_from_image



# === Scegli il componente dalle immagini presenti nella directory ===
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



# === Scegli le specifiche macchina da quelle disponibili nella directory ===
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
    # Create a Tkinter root window
    root = Tk()
    # Hide the root window
    root.withdraw()
    # Ask user where to save the file
    file_path = filedialog.asksaveasfilename(
        defaultextension=".txt",
        filetypes=[("Text files", "*.txt")],
        title="Save process plan"
    )
    return file_path



# =========================== MAIN PROGRAM =========================== #

# STEP 1 – choose image
image_path = choose_image_file(directory="dataset")
# dimensions = extract_dimensions_from_image(image_path)
# print("Extracted dimensions:", dimensions)

with open(image_path, "rb") as f:
    img_base64 = base64.b64encode(f.read()).decode()
image_data_url = f"data:image/jpeg;base64,{img_base64}"


# STEP 2 – free-text description
user_input = input("Enter a description for the part: ")
text_description = user_input
# text_description = f"{user_input}\n\nOCR-extracted dimensions: {dimensions}"


# STEP 3 – choose machine spec
machine_file = choose_machine_file(directory="machines")
with open(machine_file) as f:
    machine_spec = json.load(f)


# STEP 4 – build RAG prompt + call LLM
context_chunks = get_relevant_context(text_description, k=3)
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