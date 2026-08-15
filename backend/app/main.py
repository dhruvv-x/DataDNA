from fastapi import FastAPI
from app.core.db import init_db
from app.api.datasets import router as datasets_router

app = FastAPI(title="DataDNA API")

@app.on_event("startup")
def startup():
    init_db()

@app.get("/health")
def health():
    return {"status": "ok", "service": "datadna-api"}

app.include_router(datasets_router)
