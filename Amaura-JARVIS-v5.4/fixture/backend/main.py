"""
Backend API for fixture
App Description: fixture
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import os

app = FastAPI(title="fixture API", version="1.0.0")

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
    return {"status": "healthy", "app": "fixture"}

@app.get("/api/items")
def get_items():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, status, created_at FROM items")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "status": r[2], "created_at": r[3]} for r in rows]

@app.post("/api/items")
def create_item(item: ItemCreate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO items (title) VALUES (?)", (item.title,))
    conn.commit()
    item_id = cursor.lastrowid
    conn.close()
    return {"id": item_id, "title": item.title, "status": "active"}