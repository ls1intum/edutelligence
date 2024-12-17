from fastapi import FastAPI
import os 

ENV = os.getenv("ENV", "dev")

app = FastAPI()

@app.get("/")
def index():
    return {"message": f"HELLO {ENV}"}

@app.get("/health")
def health():
    return {"status": "ok"}