from fastapi import FastAPI

_app = FastAPI()

@_app.get("/")
def read_root():
    return {"athene": "module"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(_app, host="127.0.0.1", port=8000)