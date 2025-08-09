# authz/app.py
from fastapi import FastAPI, Request, Response
import os

app = FastAPI()
SECRET = os.getenv("NEBULA_SECRET_TOKEN", "")

@app.get("/authorize")
@app.post("/authorize")
async def authorize(req: Request):
    auth = req.headers.get("authorization", "")
    if auth == f"{SECRET}":
        # Optional: Downstream-Header setzen
        resp = Response(status_code=200)
        resp.headers["X-Auth-User"] = "nebula-gateway"
        return resp
    return Response(status_code=401)  # oder 403
