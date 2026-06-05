import os
import json
from pathlib import Path
from typing import List, Dict, Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# -------------------- Config --------------------

BASE_DIR = Path(__file__).parent
FRONTEND_PATH = BASE_DIR / "frontend"
WORKSPACE_DIR = BASE_DIR / "workspace"
WORKSPACE_DIR.mkdir(exist_ok=True)

# Use Groq via OpenAI-compatible client
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY") or "YOUR_GROQ_KEY_HERE"

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY") or "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",
)

MODEL_NAME = "llama-3.1-8b-instant"

# -------------------- FastAPI app --------------------

app = FastAPI(title="Nexus Agent – AI Workspace")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# serve static frontend if needed later
if FRONTEND_PATH.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_PATH)), name="static")


# -------------------- Pydantic models --------------------

class ChatRequest(BaseModel):
    message: str


class FileInfo(BaseModel):
    name: str
    url: str


class ChatResponse(BaseModel):
    reply: str
    files: List[FileInfo]


# -------------------- Tools implementation --------------------

def create_workspace_file(filename: str, content: str) -> str:
    """
    Create a file in the /workspace directory (safe path).
    """
    safe_name = os.path.basename(filename)
    if not safe_name:
        safe_name = "output.txt"
    target = WORKSPACE_DIR / safe_name
    try:
        target.write_text(content, encoding="utf-8")
        return f"SUCCESS: File '{safe_name}' created in the Nexus workspace."
    except Exception as e:
        return f"FAILED: Could not create file due to error: {e}"


def list_workspace_files() -> List[FileInfo]:
    files: List[FileInfo] = []
    for p in WORKSPACE_DIR.iterdir():
        if p.is_file():
            files.append(FileInfo(name=p.name, url=f"/files/{p.name}"))
    return files


# Tool schema for Groq (function-calling)
NEXUS_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_workspace_file",
            "description": (
                "Create a file in the Nexus workspace when the user asks you to generate code, "
                "documents, or project files (e.g. README.md, main.py, notes.txt, report.md, etc.)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the file to create, for example 'README.md' or 'main.py'.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full content of the file to write.",
                    },
                },
                "required": ["filename", "content"],
            },
        },
    }
]


def run_nexus_agent(user_message: str) -> str:
    """
    Send the user message to Groq with tool support,
    execute any tool calls (file creation), and return final reply.
    """

    if GROQ_API_KEY in (None, "", "YOUR_GROQ_KEY_HERE"):
        # Fallback demo mode
        return (
            "Nexus Agent is running in DEMO MODE because GROQ_API_KEY is not set.\n\n"
            "Your message was:\n" + user_message
        )

    system_prompt = (
        "You are Nexus Agent, an advanced AI workspace assistant.\n"
        "- You can reason deeply, write and refactor code, and plan multi-step solutions.\n"
        "- When the user asks to create, save, or generate files (code, docs, notes, reports), "
        "use the create_workspace_file tool to write them into the workspace.\n"
        "- Prefer to create meaningful, complete files when asked (for example: full FastAPI app, "
        "project README, config files, etc.).\n"
        "- After using tools, clearly explain to the user which files you created and what is inside.\n"
        "- Be concise but precise in your explanations."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    # First call: allow tools
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        tools=NEXUS_TOOLS,
        tool_choice="auto",
        max_tokens=800,
    )

    message = response.choices[0].message
    tool_calls = getattr(message, "tool_calls", None)

    # If no tools requested, return the text directly
    if not tool_calls:
        return message.content or ""

    # Execute each tool call
    messages.append({
        "role": "assistant",
        "tool_calls": [tc.to_dict() for tc in tool_calls],
        "content": message.content or "",
    })

    for tool_call in tool_calls:
        name = tool_call.function.name

        try:
            args = json.loads(tool_call.function.arguments)
        except Exception:
            args = {}

        if name == "create_workspace_file":
            filename = args.get("filename", "output.txt")
            content = args.get("content", "")
            result = create_workspace_file(filename=filename, content=content)
        else:
            result = f"UNKNOWN_TOOL: {name}"

        messages.append(
            {
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": name,
                "content": result,
            }
        )

    # Second call: let the model summarize after tools executed
    final = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        max_tokens=800,
    )

    return final.choices[0].message.content or ""


# -------------------- Routes --------------------

@app.get("/", response_class=HTMLResponse)
async def serve_frontend() -> HTMLResponse:
    """
    Serve the main Nexus Agent workspace UI.
    """
    html_file = FRONTEND_PATH / "index.html"
    if not html_file.exists():
        return HTMLResponse("<h1>index.html not found</h1>", status_code=404)
    return HTMLResponse(html_file.read_text(encoding="utf-8"))


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint: sends message to Nexus Agent and returns reply + current files.
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    reply = run_nexus_agent(req.message.strip())
    files = list_workspace_files()
    return ChatResponse(reply=reply, files=files)


@app.get("/api/files")
async def list_files() -> Dict[str, List[FileInfo]]:
    """
    List files available in the workspace.
    """
    return {"files": list_workspace_files()}


@app.get("/files/{filename}")
async def get_file(filename: str):
    """
    Download/open a file from the workspace.
    """
    safe_name = os.path.basename(filename)
    target = WORKSPACE_DIR / safe_name
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(target), filename=safe_name)


# -------------------- Entrypoint --------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
