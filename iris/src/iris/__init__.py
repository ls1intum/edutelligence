import os

# Only this variable prevents the 1DS uploader thread that races interpreter shutdown and aborts the process.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
