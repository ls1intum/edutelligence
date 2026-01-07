import weaviate
from weaviate.collections import Collection
from weaviate.collections.classes.types import GeoCoordinate
from tqdm import tqdm
from typing import List
import json
from datetime import date, datetime

client = weaviate.connect_to_local(
    host="localhost",
    port=8001,
    grpc_port=50051
)


def export_data(collection_src: Collection) -> List:
    objects = list()
    for q in tqdm(collection_src.iterator(include_vector=True)):
        object = q.properties
        for k, v in object.items():
            # Convert datetime and date objects to ISO 8601 strings
            if isinstance(v, (datetime, date)):
                object[k] = v.isoformat()
            # Convert GeoCoordinates to dict
            if isinstance(v, GeoCoordinate):
                object[k] = v._to_dict()

        for k, v in q.vector.items():
            object[f"vector_{k}"] = v
        object["uuid"] = str(q.uuid)
        objects.append(object)

    return objects


def save_objects(coll_name: str, coll_objects: List):
    with open(f"data_{coll_name}.json", "w") as f:
        json.dump(coll_objects, f, indent=2)
    return True


obj_count = 0
for c_name in client.collections.list_all(simple=True):
    print(f"Backing up {c_name}")

    # Back up objects
    collection = client.collections.get(c_name)
    if collection.config.get().multi_tenancy_config.enabled:
        mt_objects = dict()
        for tenant in collection.tenants.get():
            tenant_collection = collection.with_tenant(tenant)
            mt_coll_objects = export_data(tenant_collection)
            mt_objects[tenant] = mt_coll_objects
            obj_count += len(mt_coll_objects)
            print(f"Tenant {tenant} for Collection {c_name} saved with {len(mt_objects)} objects")
        save_objects(c_name, mt_objects)

    else:
        coll_objects = export_data(collection)
        obj_count += len(coll_objects)
        save_objects(c_name, coll_objects)
        print(f"Collection {c_name} saved with {len(coll_objects)} objects")

    # Back up schema
    coll_config = collection.config.get().to_dict()
    with open(f"schema_{c_name}.json", "w") as f:
        json.dump(coll_config, f, indent=2)
    print(f"Schema for Collection {c_name} saved")


client.close()