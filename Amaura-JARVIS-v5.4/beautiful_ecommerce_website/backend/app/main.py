"""FastAPI application for beautiful_ecommerce_website-backend."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import router

app = FastAPI(
    title="beautiful_ecommerce_website-backend",
    description="beautiful_ecommerce_website API backend",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"message": "Welcome to beautiful_ecommerce_website-backend API", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
