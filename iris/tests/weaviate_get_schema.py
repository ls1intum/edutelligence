import requests

url = "http://localhost:8001/v1/schema"
response = requests.get(url)
schema = response.json()

# Print classes
classes = [cls["class"] for cls in schema.get("classes", [])]
print("Klassen:", classes)

# Show details of class
for cls in schema.get("classes", []):
    print(f"Class: {cls['class']}")
    for prop in cls.get("properties", []):
        print(f"  - {prop['name']}: {prop['dataType']}")
