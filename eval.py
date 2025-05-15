import os
from dotenv import load_dotenv
import openai
from openai import OpenAI
import tkinter as tk
from tkinter import filedialog

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
ENGINE = "gpt-4o"
client = OpenAI()

instructions = """
You are an assistant, take the input txt and the query and answer correctly. 
Answer the question with one word. You are not allowed to add any extra words, spaces or punctuation, even at the end of the answer.
"""

# Compute the MRR for the initial facing operation
# Given constants C=450 and n=0.2 use the Taylor's formula to compute the tool life in min for the tool used for facing operation
# Compute the cutting speed for the initial facing operation
question = "Compute the cutting speed for the initial facing operation"

# === Ask user to select a .txt file ===
root = tk.Tk()
root.withdraw()
txt_file_path = filedialog.askopenfilename(
    title="Select process plan .txt file",
    filetypes=[("Text files", "*.txt")]
)
root.destroy()

if not txt_file_path:
    print("No file selected. Exiting.")
    exit(1)

with open(txt_file_path, "r", encoding="utf-8") as f:
    response = f.read()

completion = client.chat.completions.create(
     model=ENGINE,
     messages=[
        {"role": "developer", "content": instructions},
        {"role": "user", "content": response},
        {"role": "user", "content": question}
    ]
)

print(completion.choices[0].message.content)