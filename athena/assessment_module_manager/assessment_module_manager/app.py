from fastapi import FastAPI

description = """
This is the Athena API. You are interacting with the Assessment Module Manager, 
which is responsible for deciding which assessment modules to run when there are
new submissions or new feedback.

You would usually connect this API with an LMS of your choice to get suggestions
from any of the modules that are available. You can find a list of modules at
the [/modules](/modules) endpoint.
"""

app = FastAPI(
    title="Athena API",
    description=description,
    version="0.1.0"
)
