"""Process boot identity.

A fresh UUID per process start, reported through the health endpoint.
Artemis compares it between health checks: a changed boot id proves every
in-flight ingestion job died with the old process, so the jobs can be
re-dispatched immediately instead of waiting for a staleness timeout. A
DOWN-then-UP observation cannot give that guarantee, because a fast restart
can hide entirely between two polls.
"""

import uuid

BOOT_ID = str(uuid.uuid4())
