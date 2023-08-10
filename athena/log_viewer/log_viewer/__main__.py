from typing import Annotated, List
import os
import secrets

from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import docker

app = FastAPI()
security = HTTPBasic()
LOGS_PWD = os.environ["LOGS_PASSWORD"]

@app.get("/logs", response_class=HTMLResponse)
def get_docker_logs(credentials: Annotated[HTTPBasicCredentials, Depends(security)]):
    """Get logs from all docker containers"""
    if credentials.username != "athena" or secrets.compare_digest(credentials.password.encode("utf-8"), LOGS_PWD.encode("utf-8")) is False:
        return {"message": "Incorrect username or password"}

    client = docker.from_env()

    # Get logs from all containers
    all_logs: List[str] = []
    for container in client.containers.list():
        logs = container.logs(tail=200, timestamps=True).decode('utf-8').split('\n')
        all_logs.extend(logs)

    # Sort logs by timestamp
    sorted_logs = sorted(all_logs)

    # Generate HTML
    logs_html = "<html><body>"
    # container list
    logs_html += "<h1>Containers</h1>"
    logs_html += "<ul>"
    for container in client.containers.list():
        logs_html += f"<li>{container.name}</li>"
    logs_html += "</ul>"
    # logs
    logs_html += "<h1>Logs</h1>"
    for log in sorted_logs:
        logs_html += f"<code>{log}</code>"
    # styling
    logs_html += "<style>body { font-family: sans-serif; } code { display: block; white-space: pre-wrap; word-wrap: break-word; }</style>"
    logs_html += "</body></html>"

    return logs_html



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4998)
