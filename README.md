# Yefhamak backend

## Step 1 setup
1. python -m venv .venv
2. Activate it:  Windows: .venv\Scripts\activate   |   Mac/Linux: source .venv/bin/activate
3. pip install -r requirements.txt
4. Copy .env.example to .env and paste your Neon connection strings
5. uvicorn app.main:app --reload
6. Open http://127.0.0.1:8000/health and http://127.0.0.1:8000/health/db
   (interactive docs: http://127.0.0.1:8000/docs)
