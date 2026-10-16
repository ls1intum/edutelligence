"""The credential Iris presents to Artemis on every callback of one run.

Artemis issues one token per run and sends it in the execution settings. Iris only echoes
it back as ``Authorization: Bearer <token>``; it never reads it, logs it or uses it as an
identifier. The run id, which is not a secret, identifies the run.

The token is wrapped so that it cannot leak by accident. Tracing (Langfuse records the
arguments of observed functions by walking ``__dict__``, ``__slots__`` and Pydantic dumps),
error reporting and logging all see only a mask. Even Pydantic's ``SecretStr`` is not enough
here: it keeps the value in an attribute, which the Langfuse serializer exports.
"""

from typing import Any

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

MASK = "**********"


class CallbackToken:
    """An opaque callback token. ``reveal()`` is for building the Authorization header only."""

    # The value lives in a closure, not in an attribute: whatever walks the object's slots or
    # attributes finds a function, never the value.
    __slots__ = ("_reveal",)

    def __init__(self, value: str):
        if not isinstance(value, str) or not value:
            raise ValueError("A callback token must be a non-empty string")
        self._reveal = lambda: value

    def reveal(self) -> str:
        """Return the token, for the Authorization header of a callback."""
        return self._reveal()

    def authorization_header(self) -> str:
        """Return the value of the Authorization header that presents this token."""
        return f"Bearer {self._reveal()}"

    def __repr__(self) -> str:
        return f"CallbackToken('{MASK}')"

    def __str__(self) -> str:
        return MASK

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CallbackToken) and other.reveal() == self.reveal()

    def __hash__(self) -> int:
        return hash(self.reveal())

    @classmethod
    def _coerce(cls, value: Any) -> "CallbackToken":
        if isinstance(value, CallbackToken):
            return value
        return cls(value)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        del source, handler
        from_str = core_schema.no_info_after_validator_function(
            cls._coerce, core_schema.str_schema(min_length=1)
        )
        return core_schema.json_or_python_schema(
            json_schema=from_str,
            python_schema=core_schema.union_schema(
                [core_schema.is_instance_schema(cls), from_str]
            ),
            # Every dump, Python or JSON, shows the mask: nothing in Iris sends this model back
            # out, and every place that dumps it (tracing, logs, error reports) must not see the token.
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda _value: MASK, when_used="always"
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        del schema
        return handler(core_schema.str_schema(min_length=1))
