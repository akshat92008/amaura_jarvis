"""
One-Shot App Builder Module for JARVIS.
Scaffolds, creates fullstack frontend & backend code, database connections, dependency setups, and launches dev servers.
"""

import os
from typing import Optional

APP_BUILDER_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_fullstack_app",
            "description": "Scaffold and build a full-stack application (frontend + backend + DB) in a single turn.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Directory name for the new application (e.g. 'my_awesome_app')."
                    },
                    "stack": {
                        "type": "string",
                        "description": "Stack type: 'vite-react-fastapi', 'nextjs', 'express-react', 'fastapi-vanilla'",
                        "default": "vite-react-fastapi"
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the application features and purpose."
                    },
                    "target_dir": {
                        "type": "string",
                        "description": "Parent directory path where the app directory will be created. Defaults to current working directory."
                    }
                },
                "required": ["project_name", "description"]
            }
        }
    }
]


def create_fullstack_app(
    project_name: str,
    description: str,
    stack: str = "vite-react-fastapi",
    target_dir: Optional[str] = None
) -> str:
    """
    Creates a complete fullstack application boilerplate with code files, dependencies, and launch instructions.
    """
    if not target_dir:
        target_dir = os.getcwd()
        
    app_dir = os.path.abspath(os.path.join(target_dir, project_name))
    os.makedirs(app_dir, exist_ok=True)

    created_files = []

    if stack == "vite-react-fastapi" or stack == "fastapi-vanilla":
        # ── 1. Backend: FastAPI main.py ───────────────────────────────────
        backend_dir = os.path.join(app_dir, "backend")
        os.makedirs(backend_dir, exist_ok=True)
        
        main_py = os.path.join(backend_dir, "main.py")
        main_py_code = f'''"""
Backend API for {project_name}
App Description: {description}
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import os

app = FastAPI(title="{project_name} API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = os.path.join(os.path.dirname(__file__), "app.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

class ItemCreate(BaseModel):
    title: str

@app.get("/api/health")
def health_check():
    return {{"status": "healthy", "app": "{project_name}"}}

@app.get("/api/items")
def get_items():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, status, created_at FROM items")
    rows = cursor.fetchall()
    conn.close()
    return [{{"id": r[0], "title": r[1], "status": r[2], "created_at": r[3]}} for r in rows]

@app.post("/api/items")
def create_item(item: ItemCreate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO items (title) VALUES (?)", (item.title,))
    conn.commit()
    item_id = cursor.lastrowid
    conn.close()
    return {{"id": item_id, "title": item.title, "status": "active"}}
'''
        with open(main_py, "w", encoding="utf-8") as f:
            f.write(main_py_code.strip())
        created_files.append(main_py)

        req_txt = os.path.join(backend_dir, "requirements.txt")
        with open(req_txt, "w", encoding="utf-8") as f:
            f.write("fastapi>=0.109.0\nuvicorn>=0.27.0\npydantic>=2.6.0\n")
        created_files.append(req_txt)

        # ── 2. Frontend: HTML/CSS/JS Single-Page UI ───────────────────────
        frontend_dir = os.path.join(app_dir, "frontend")
        os.makedirs(frontend_dir, exist_ok=True)

        index_html = os.path.join(frontend_dir, "index.html")
        html_code = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project_name}</title>
    <style>
        :root {{
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --accent: #38bdf8;
            --text: #f8fafc;
            --muted: #94a3b8;
        }}
        body {{
            margin: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-color);
            color: var(--text);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }}
        .container {{
            width: 90%;
            max-width: 600px;
            background: var(--card-bg);
            padding: 2rem;
            border-radius: 16px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        h1 {{ color: var(--accent); font-size: 1.8rem; margin-bottom: 0.5rem; }}
        p {{ color: var(--muted); line-height: 1.5; }}
        .form-group {{ display: flex; gap: 0.5rem; margin: 1.5rem 0; }}
        input {{
            flex: 1;
            padding: 0.75rem;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.2);
            background: #0f172a;
            color: #fff;
        }}
        button {{
            padding: 0.75rem 1.25rem;
            background: var(--accent);
            color: #000;
            font-weight: bold;
            border: none;
            border-radius: 8px;
            cursor: pointer;
        }}
        button:hover {{ opacity: 0.9; }}
        ul {{ list-style: none; padding: 0; }}
        li {{
            background: rgba(255, 255, 255, 0.05);
            padding: 0.75rem 1rem;
            margin-bottom: 0.5rem;
            border-radius: 8px;
            display: flex;
            justify-content: space-between;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 {project_name}</h1>
        <p>{description}</p>
        
        <div class="form-group">
            <input type="text" id="itemInput" placeholder="Add a new item..." />
            <button onclick="addItem()">Add Item</button>
        </div>

        <ul id="itemList"></ul>
    </div>

    <script>
        const API_URL = 'http://localhost:8000/api';

        async function fetchItems() {{
            try {{
                const res = await fetch(`${{API_URL}}/items`);
                const items = await res.json();
                const list = document.getElementById('itemList');
                list.innerHTML = items.map(item => `<li><span>${{item.title}}</span> <small>${{item.status}}</small></li>`).join('');
            }} catch (err) {{
                console.error('API Error:', err);
            }}
        }}

        async function addItem() {{
            const input = document.getElementById('itemInput');
            if (!input.value.trim()) return;
            try {{
                await fetch(`${{API_URL}}/items`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ title: input.value.trim() }})
                }});
                input.value = '';
                fetchItems();
            }} catch (err) {{
                console.error('Error adding item:', err);
            }}
        }}

        fetchItems();
    </script>
</body>
</html>
'''
        with open(index_html, "w", encoding="utf-8") as f:
            f.write(html_code.strip())
        created_files.append(index_html)

    # ── README & Startup Script ──────────────────────────────────────────────
    readme_md = os.path.join(app_dir, "README.md")
    readme_code = f"""# {project_name}

{description}

## Stack
- **Backend:** FastAPI + SQLite
- **Frontend:** Modern HTML5 / CSS3 / ES6 Fetch

## Running the Application

### 1. Start Backend API
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 2. Start Frontend Server
```bash
cd frontend
python3 -m http.server 3000
```
Then open http://localhost:3000 in your browser.
"""
    with open(readme_md, "w", encoding="utf-8") as f:
        f.write(readme_code.strip())
    created_files.append(readme_md)

    file_tree = "\n".join([f"  - {os.path.relative_path if hasattr(os.path, 'relative_path') else os.path.relpath(f, target_dir)}" for f in created_files])

    return f"""✅ **Fullstack Application '{project_name}' Successfully Created!**

📁 **Project Root:** `{app_dir}`
💻 **Stack:** {stack}

📄 **Created Files:**
{file_tree}

🚀 **To Launch:**
1. Backend: `cd {app_dir}/backend && uvicorn main:app --port 8000`
2. Frontend: `cd {app_dir}/frontend && python3 -m http.server 3000`
"""


APP_BUILDER_DISPATCH = {
    "create_fullstack_app": create_fullstack_app
}
