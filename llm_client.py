# llm_client.py
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def call_llm(prompt: str, image_data_url: str, model: str = "gpt-4o") -> str:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}}
            ]
        }
    ]
    resp = client.chat.completions.create(model=model, messages=messages)
    return resp.choices[0].message.content


def call_llm_with_system(prompt: str, image_data_url: str, system_message: str, model: str = "gpt-4o") -> str:
    """
    Send a prompt + image + system message to the vision model.
    Keeps `call_llm()` unchanged for other uses.
    """
    messages = [
        {"role": "system", "content": system_message},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]
    resp = client.chat.completions.create(model=model, messages=messages)
    return resp.choices[0].message.content
