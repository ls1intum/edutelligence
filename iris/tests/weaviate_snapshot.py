import weaviate
import json
import os

def fetch_to_dict(fetch_result):
    return {
        "objects": [
            {
                "uuid": obj.uuid,
                "properties": obj.properties,
                "vector": obj.vector
            }
            for obj in fetch_result.objects
        ]
    }

# -------------------------------
# Connection to Weaviate DB
# -------------------------------
client = weaviate.connect_to_local(
    host="localhost",
    port=8001,
    grpc_port=50051
)

# -------------------------------
# Export objects of each class
# -------------------------------

snapshot = {"LectureUnits": fetch_to_dict(
    client.collections.get("LectureUnits").query.fetch_objects(
        limit=10000, include_vector=True
    )
), "Lectures": fetch_to_dict(
    client.collections.get("Lectures").query.fetch_objects(
        limit=10000, include_vector=True
    )
), "LectureTranscriptions": fetch_to_dict(
    client.collections.get("LectureTranscriptions").query.fetch_objects(
        limit=10000, include_vector=True
    )
), "Faqs": fetch_to_dict(
    client.collections.get("Faqs").query.fetch_objects(
        limit=10000, include_vector=True
    )
), "LectureUnitSegments": fetch_to_dict(
    client.collections.get("LectureUnitSegments").query.fetch_objects(
        limit=10000, include_vector=True
    )
)}

# TODO: check why export is empty (check DB and query results)

# Snapshot in JSON-Datei speichern
with open("weaviate_snapshot.json", "w", encoding="utf-8") as f:
    json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print(f"Saved: weaviate_snapshot.json ({len(snapshot.values())} Objects)")

# -------------------------------
# Verbindung schließen
# -------------------------------
client.close()
print("Snapshot exported ✅")

