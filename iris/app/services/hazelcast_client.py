import hazelcast
from app.config import settings

hazelcast_client = hazelcast.HazelcastClient(
    cluster_members=[
        f"{settings.pyris.cache.hazelcast.host}:\
        {settings.pyris.cache.hazelcast.port}"
    ],
)
