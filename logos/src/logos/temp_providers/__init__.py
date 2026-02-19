"""
Temporary (in-memory) LLM provider support for Logos.

Allows ephemeral providers (e.g. LMStudio on a Mac via tunnel) to register,
auto-discover their models, and be health-monitored — without touching the DB.
"""
