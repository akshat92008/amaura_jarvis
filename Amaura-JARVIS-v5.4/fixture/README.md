# fixture

fixture

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