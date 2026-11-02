import os

# Must run before onnxruntime is imported: only this variable prevents the 1DS uploader thread
# that races interpreter shutdown and aborts the process. An empty value would enable it.
if not os.environ.get("ORT_DISABLE_TELEMETRY"):
    os.environ["ORT_DISABLE_TELEMETRY"] = "1"
