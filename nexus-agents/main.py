"""
NEXUS-AGENTS LITE  —  main.py
==============================
100% free to run. No subscriptions needed.
Uses: FastAPI + SQLite (no Postgres needed) + OpenAI API (free tier works)

HOW TO RUN:
  1. pip install fastapi uvicorn openai aiofiles
  2. Set your OpenAI key:
       Windows:  set OPENAI_API_KEY=sk-...
       Mac/Linux: export OPENAI_API_KEY=sk-...
  3. python main.py
  4. Open http://localhost:8000 in your browser
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

# ── Setup ────────────────────────────────────────────────────────────
# ── Setup ────────────────────────────────────────────────────────────
# DELETE OR COMMENT OUT THIS LINE:
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# PASTE YOUR REAL KEY DIRECTLY HERE AS A STR:
OPENAI_API_KEY = "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"
DB_PATH = "nexus.db"
FRONTEND_PATH = Path(__file__).parent / "frontend"

app = FastAPI(title="Nexus-Agents Lite")

# Serve the frontend HTML/CSS/JS
if FRONTEND_PATH.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_PATH)), name="static")

# ── Database (SQLite — zero install needed) ───────────────────────────
def get_db():
    """Creates and returns a connection that outputs rows as dictionary-like objects."""
    conn = sqlite3.connect("nexus.db", timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    """Create tables on first run."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            role        TEXT NOT NULL,
            status      TEXT DEFAULT 'idle',
            current_job TEXT DEFAULT 'Waiting for tasks...',
            tasks_done  INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id            TEXT PRIMARY KEY,
            title         TEXT NOT NULL,
            description   TEXT NOT NULL,
            assigned_to   TEXT,
            status        TEXT DEFAULT 'queued',
            result        TEXT,
            needs_approval INTEGER DEFAULT 0,
            approved      INTEGER DEFAULT 0,
            created_at    TEXT DEFAULT (datetime('now')),
            finished_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT,
            level      TEXT DEFAULT 'INFO',
            message    TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Seed 3 starter agents if the table is empty
        INSERT OR IGNORE INTO agents (id, name, role, status) VALUES
            ('agent-priya',  'Priya',  'Sales Agent',   'idle'),
            ('agent-raj',    'Raj',    'Support Agent', 'idle'),
            ('agent-arjun',  'Arjun',  'Finance Agent', 'idle');
    """)
    conn.commit()
    conn.close()

# ── Pydantic models (what the API accepts) ────────────────────────────
class TaskRequest(BaseModel):
    title: str
    description: str
    needs_approval: bool = False   # True = ask human before running

class ApprovalDecision(BaseModel):
    approved: bool

# ── Helper: add a log entry ───────────────────────────────────────────
def add_log(agent_name, message, level="INFO", conn=None):
    opened_here = False
    if conn is None:
        conn = get_db()
        opened_here = True
        
    try:
        conn.execute(
            "INSERT INTO logs (agent_name, level, message) VALUES (?, ?, ?)",
            (agent_name, level, message)
        )
        conn.commit()
    except Exception as e:
        print(f"⚠️ Failed to write log: {e}")
    finally:
        if opened_here:
            conn.close()

# ── Helper: pick the right agent for a task ───────────────────────────
def pick_agent(description: str) -> str:
    """Very simple routing: keywords decide which agent gets the task."""
    desc = description.lower()
    if any(w in desc for w in ["invoice", "payment", "money", "₹", "price quote", "bill"]):
        return "agent-arjun"
    if any(w in desc for w in ["complaint", "problem", "issue", "help", "support", "broken"]):
        return "agent-raj"
    return "agent-priya"   # default: sales
# ── Agent Actions/Tools Definition ────────────────────────────────────
def create_business_file(filename: str, content: str) -> str:
    """A real Python tool that lets the agent create files on your computer."""
    try:
        # Keep it safe by extracting just the file name
        safe_name = os.path.basename(filename)
        with open(safe_name, "w", encoding="utf-8") as f:
            f.write(content)
        return f"SUCCESS: Successfully created the file '{safe_name}' on the user's drive."
    except Exception as e:
        return f"FAILED: Could not create file due to error: {str(e)}"

# This schema tells Groq exactly what the tool does and what arguments it needs
BUSINESS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_business_file",
            "description": "Use this tool to create a local file (like a CSV spreadsheet, financial ledger, or TXT report) on the computer whenever the user asks to save, log, or generate business documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The name of the file to generate. For example: 'competitor_prices.csv' or 'sales_lead_report.txt'."
                    },
                    "content": {
                        "type": "string",
                        "description": "The full body text, table rows, comma-separated CSV data, or text content to write into the file."
                    }
                },
                "required": ["filename", "content"]
            }
        }
    }
]
# ── Helper: actually call OpenAI ──────────────────────────────────────
def run_agent_with_ai(agent_name: str, agent_role: str, task_description: str) -> str:
    """
    Sends the task to Groq and executes system tools if the AI decides
    it needs to perform a digital workforce operation.
    """
    if not OPENAI_API_KEY:
        return (
            f"[DEMO MODE — no API key set]\n\n"
            f"Hi! I'm {agent_name}, your {agent_role}. "
            f"I would handle this task: '{task_description}'"
        )

    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=OPENAI_API_KEY
    )

    system_prompts = {
        "Sales Agent": (
            "You are Priya, a friendly sales agent for a Jaipur business. "
            "Reply in a warm, professional tone. Keep replies short (3-5 sentences). "
            "You have access to tools to write files. If the user asks for a report or log, use them."
        ),
        "Support Agent": (
            "You are Raj, a patient customer support agent. "
            "Acknowledge the problem, apologize if needed, and suggest a clear solution. "
            "You can use tools to write data if logging an issue is requested."
        ),
        "Finance Agent": (
            "You are Arjun, a precise finance agent. "
            "Help with invoices, payment queries, and pricing. "
            "Always mention that high-value transactions need manager approval. Use tools to create spreadsheets/ledgers."
        ),
    }

    system = system_prompts.get(agent_role, "You are a helpful AI assistant.")

    # 1. Build the conversation history array
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": task_description},
    ]

    # 2. Call Groq with our tool definitions passed in
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        tools=BUSINESS_TOOLS,
        tool_choice="auto",
        max_tokens=500,
    )

    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls

    # 3. Check if the AI decided to execute a computer action
    if tool_calls:
        # Append the tool call notification to messages tracking
        messages.append(response_message)
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            
            # Safely parse arguments sent by the LLM
            try:
                function_args = json.loads(tool_call.function.arguments)
            except Exception:
                function_args = {}

            if function_name == "create_business_file":
                target_file = function_args.get("filename", "output.txt")
                file_data = function_args.get("content", "")

                # Run the actual computer file generation tool
                tool_result = create_business_file(filename=target_file, content=file_data)
                
                # Append the execution result to give back to the AI model
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": tool_result,
                })

        # 4. Get a final summary text back from the AI now that its task is fulfilled
        final_response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=400
        )
        return final_response.choices[0].message.content

    # If no tool was required, return standard text response
    return response_message.content

# ── Routes ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the dashboard HTML."""
    html_file = FRONTEND_PATH / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Frontend not found. Make sure frontend/index.html exists.</h1>"


@app.get("/api/agents")
def get_agents():
    conn = get_db()
    agents = [dict(row) for row in conn.execute("SELECT * FROM agents").fetchall()]
    conn.close()
    return agents


@app.get("/api/tasks")
def get_tasks():
    conn = get_db()
    tasks = [dict(row) for row in conn.execute(
        "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 50"
    ).fetchall()]
    conn.close()
    return tasks


@app.get("/api/logs")
def get_logs():
    conn = get_db()
    logs = [dict(row) for row in conn.execute(
        "SELECT * FROM logs ORDER BY created_at DESC LIMIT 30"
    ).fetchall()]
    conn.close()
    return logs


@app.post("/api/tasks")
def create_task(req: TaskRequest, background_tasks: BackgroundTasks):
    """Create a new task and pass execution to a background thread."""
    task_id    = str(uuid.uuid4())[:8]
    agent_id   = pick_agent(req.description)

    conn = get_db()

    agent = conn.execute(
        "SELECT * FROM agents WHERE id = ?", (agent_id,)
    ).fetchone()
    
    agent_name = agent["name"] if agent else "Unknown"
    agent_role = agent["role"] if agent else "Assistant"

    conn.execute(
        """INSERT INTO tasks (id, title, description, assigned_to, status, needs_approval)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            task_id,
            req.title,
            req.description,
            agent_id,
            "awaiting_approval" if req.needs_approval else "in_progress",
            1 if req.needs_approval else 0,
        )
    )

    if req.needs_approval:
        conn.execute(
            "UPDATE agents SET status='idle', current_job=? WHERE id=?",
            ("Waiting for approval on a task...", agent_id)
        )
        add_log("Manager", f"🔒 Task '{req.title}' needs approval before {agent_name} can run it", "GATE", conn=conn)
    else:
        conn.execute(
            "UPDATE agents SET status='running', current_job=? WHERE id=?",
            (f"Working on: {req.title}", agent_id)
        )
        add_log("Manager", f"📋 Assigned '{req.title}' → {agent_name}", "INFO", conn=conn)

    conn.commit()
    conn.close()

    # 🚀 Run the AI agent in the background so the frontend doesn't freeze!
    if not req.needs_approval:
        background_tasks.add_task(_execute_task, task_id, agent_id, agent_name, req.description, agent_role)

    return {"task_id": task_id, "assigned_to": agent_name, "status": "created"}


def _execute_task(task_id: str, agent_id: str, agent_name: str, description: str, role: str):
    """Run the task through OpenAI and save the result."""
    add_log(agent_name, f"🤔 Thinking about: {description[:60]}...", "INFO")

    try:
        result = run_agent_with_ai(agent_name, role, description)

        conn = get_db()
        conn.execute(
            """UPDATE tasks
               SET status='completed', result=?, finished_at=datetime('now')
               WHERE id=?""",
            (result, task_id)
        )
        conn.execute(
            "UPDATE agents SET status='idle', tasks_done=tasks_done+1, current_job='Waiting for tasks...' WHERE id=?",
            (agent_id,)
        )
        conn.commit()
        conn.close()

        add_log(agent_name, f"✅ Completed task — replied in {len(result)} chars", "OK")

    except Exception as e:
        conn = get_db()
        conn.execute(
            "UPDATE tasks SET status='failed', result=? WHERE id=?",
            (str(e), task_id)
        )
        conn.execute(
            "UPDATE agents SET status='idle', current_job='Waiting for tasks...' WHERE id=?",
            (agent_id,)
        )
        conn.commit()
        conn.close()
        add_log(agent_name, f"❌ Task failed: {str(e)}", "ERROR")


@app.post("/api/tasks/{task_id}/approve")
def approve_task(task_id: str, decision: ApprovalDecision, background_tasks: BackgroundTasks):
    """Human approves or rejects a task that was waiting."""
    conn = get_db()
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()

    if not task:
        conn.close()
        raise HTTPException(404, "Task not found")

    if task["status"] != "awaiting_approval":
        conn.close()
        raise HTTPException(400, f"Task is '{task['status']}', not waiting for approval")

    if decision.approved:
        conn.execute(
            "UPDATE tasks SET status='in_progress', approved=1 WHERE id=?", (task_id,)
        )
        agent = conn.execute(
            "SELECT * FROM agents WHERE id=?", (task["assigned_to"],)
        ).fetchone()
        conn.execute(
            "UPDATE agents SET status='running', current_job=? WHERE id=?",
            (f"Working on: {task['title']}", agent["id"])
        )
        conn.commit()
        conn.close()

        add_log("Human", f"✅ Approved task '{task['title']}'", "INFO")
        
        # 🚀 Use background task here too!
        background_tasks.add_task(_execute_task, task_id, agent["id"], agent["name"], task["description"], agent["role"])
    else:
        conn.execute(
            "UPDATE tasks SET status='rejected' WHERE id=?", (task_id,)
        )
        conn.commit()
        conn.close()
        add_log("Human", f"❌ Rejected task '{task['title']}'", "WARN")

    return {"status": "approved" if decision.approved else "rejected"}


@app.get("/api/stats")
def get_stats():
    conn = get_db()
    total_tasks   = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='completed'").fetchone()[0]
    active_agents = conn.execute("SELECT COUNT(*) FROM agents WHERE status='running'").fetchone()[0]
    pending       = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='awaiting_approval'").fetchone()[0]
    conn.close()
    return {
        "tasks_completed": total_tasks,
        "active_agents":   active_agents,
        "pending_approvals": pending,
        "hours_saved":     round(total_tasks * 0.25, 1),
    }


# ── Start the server ──────────────────────────────────────────────────
# ── Start the server ──────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    print("\n" + "="*50)
    print("  NEXUS-AGENTS LITE")
    print("="*50)

    if not OPENAI_API_KEY:
        print("\n⚠️  No OPENAI_API_KEY found.")
        print("   The app will run in DEMO MODE (fake AI responses).")
        print("   To get real AI: set OPENAI_API_KEY=sk-... in your terminal\n")
    else:
        print("\n✅ OpenAI API key found — real AI responses enabled!\n")

    init_db()
    print("✅ Database ready (nexus.db)")
    print("\n🚀 Starting server...")
    
    # Dynamically grab the port assigned by the cloud platform
    port = int(os.environ.get("PORT", 8000))
    print(f"   Starting on port: {port}\n")

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
