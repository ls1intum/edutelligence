import weaviate
import json
import os

# -------------------------------
# Connection to Weaviate DB
# -------------------------------
client = weaviate.connect_to_local(
    host="localhost",
    port=8001,
    grpc_port=50051
)

# -------------------------------
# Directory for snapshots
# -------------------------------
snapshot_dir = "weaviate_snapshot"
os.makedirs(snapshot_dir, exist_ok=True)

# -------------------------------
# Export objects of each class
# -------------------------------

snapshot = {}

snapshot["LectureUnits"] = client.collections.get("LectureUnits").query.fetch_objects(limit=10000, include_vector=True)
snapshot["Lectures"] = client.collections.get("Lectures").query.fetch_objects(limit=10000, include_vector=True)
snapshot["LectureTranscriptions"] = client.collections.get("LectureTranscriptions").query.fetch_objects(limit=10000, include_vector=True)
snapshot["Faqs"] = client.collections.get("Faqs").query.fetch_objects(limit=10000, include_vector=True)
snapshot["LectureUnitSegments"] = client.collections.get("LectureUnitSegments").query.fetch_objects(limit=10000, include_vector=True)

# TODO: find way to conver snapshot to dict, so it can be dumped to json

# Snapshot in JSON-Datei speichern
with open("weaviate_snapshot.json", "w", encoding="utf-8") as f:
    json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print(f"Gespeichert: {file_path} ({len(all_objects)} Objekte)")

# -------------------------------
# Verbindung schließen
# -------------------------------
client.close()
print("Snapshot exportiert ✅")

