"""OptiBot: Gemini + File Search over the synced help-center store, with the brief's system prompt verbatim.

Google AI Studio's playground has no File Search tool, so the assistant is configured here through the API.

    python chat.py "How do I add a YouTube video?"   # one question in the terminal
    python chat.py                                   # chat UI at http://localhost:7860
"""

import sys
import time

from google import genai
from google.genai import errors, types

from config import load_config
from uploader import FileSearchStore

SYSTEM_PROMPT = """You are OptiBot, the customer-support bot for OptiSigns.com.
• Tone: helpful, factual, concise.
• Only answer using the uploaded docs.
• Max 5 bullet points; else link to the doc.
• Cite up to 3 "Article URL:" lines per reply."""

# Tried in order when the main model is overloaded (503) or rate-limited (429) on the free tier.
FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash"]

cfg = load_config()
client = genai.Client(api_key=cfg.api_key)
store = FileSearchStore.open(client, cfg.store_name, cfg.store_id)
generation_config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[types.Tool(file_search=types.FileSearch(file_search_store_names=[store.name]))],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # File Search only
)


def ask(question: str, history: list[dict] | None = None) -> str:
    contents = [
        types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part(text=_text(m["content"]))])
        for m in history or []
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))

    for model in [cfg.model] + [m for m in FALLBACK_MODELS if m != cfg.model]:
        for attempt in range(3):
            try:
                response = client.models.generate_content(model=model, contents=contents, config=generation_config)
                return response.text or "(no answer)"
            except errors.APIError as e:
                if e.code not in (429, 503):
                    raise
                time.sleep(2 * (attempt + 1))  # busy: wait a bit, then retry / move to the next model
    return "Gemini is busy right now (free tier). Please try again in a minute."


def _text(content) -> str:
    # Gradio may pass message content as a string or as a list of parts.
    if isinstance(content, str):
        return content
    return " ".join(p.get("text", "") for p in content if isinstance(p, dict))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(ask(" ".join(sys.argv[1:])))
    else:
        import gradio as gr

        gr.ChatInterface(
            fn=ask,
            title="OptiBot",
            description=f"OptiSigns support bot · {cfg.model} + Gemini File Search",
            examples=["How do I add a YouTube video?", "How do I pair a screen?", "What file types are supported?"],
        ).launch()
