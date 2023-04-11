from fastapi import FastAPI
import uvicorn

_app = FastAPI()

@_app.get("/")
def read_root():
    return {"athene": "module"}

def start():
    uvicorn.run(_app, host="127.0.0.1", port=8000)
