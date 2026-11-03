"""The credential Iris presents to Artemis on every callback of one run.

Artemis issues one token per run and sends it in the execution settings. Iris only echoes
it back as ``Authorization: Bearer <token>``; it never reads it, logs it or uses it as an
identifier. The run id, which is not a secret, identifies the run.

The token is wrapped so that it cannot leak by accident. Tracing (Langfuse records the
arguments of observed functions by walking ``__dict__``, ``__slots__`` and Pydantic dumps),
error reporting and logging all see only a mask. Even Pydantic's ``SecretStr`` is not enough
here: it keeps the value in an attribute, which the Langfuse serializer exports.
"""

import hashlib
import re
import threading
import uuid
from collections import OrderedDict
from typing import Any

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

MASK = "**********"

# The run id segment of an Artemis callback URL (".../runs/<run id>/status").
_RUN_SEGMENT = re.compile(r"(/runs/)([^/?#\s\"'<>]+)")
_HASHED_RUN_ID = re.compile(r"run-[0-9a-f]{24}")


def hash_run_id(value: str) -> str:
    """A stable id for a run that does not contain ``value``.

    Artemis versions that send no run id use the callback token as run id, so that value
    must not leave Iris in traces or error reports; this hash stands in for it there.
    """
    return "run-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


# Tokens that an Artemis without run ids uses as run ids, as registered by the callbacks of their runs.
# Their shape tells nothing: a global search token of such an Artemis is a UUID like any run id.
# Once a token had to be dropped to stay within the limit, the registry can no longer tell every
# token apart from a run id, so from then on every run id segment is scrubbed (fail closed).
_LEGACY_TOKEN_LIMIT = 10_000
_legacy_tokens: "OrderedDict[str, None]" = OrderedDict()
_legacy_tokens_lock = threading.Lock()
_legacy_tokens_dropped = False  # pylint: disable=invalid-name


def register_legacy_run_token(value: str) -> None:
    """Remember a callback token that also serves as run id, so every scrub replaces it."""
    global _legacy_tokens_dropped  # pylint: disable=global-statement,invalid-name
    with _legacy_tokens_lock:
        _legacy_tokens[value] = None
        _legacy_tokens.move_to_end(value)
        while len(_legacy_tokens) > _LEGACY_TOKEN_LIMIT:
            _legacy_tokens.popitem(last=False)
            _legacy_tokens_dropped = True


def _may_be_legacy_token(segment: str) -> bool:
    with _legacy_tokens_lock:
        return _legacy_tokens_dropped or segment in _legacy_tokens


def _is_plain_run_id(segment: str) -> bool:
    if _may_be_legacy_token(segment):
        return False
    if _HASHED_RUN_ID.fullmatch(segment):
        return True
    try:
        return str(uuid.UUID(segment)) == segment.lower()
    except ValueError:
        return False


def scrub_callback_credentials(value: Any) -> Any:
    """Replace every callback URL run id segment that is not a plain run id with its hash.

    Plain run ids are UUIDs. A segment that is no UUID, or that a callback registered as
    token (see register_legacy_run_token), is a callback token that an older Artemis expects
    in the URL. Strings inside dicts, lists and tuples are scrubbed as well.
    """
    if isinstance(value, str):
        return _RUN_SEGMENT.sub(
            lambda match: (
                match.group(0)
                if _is_plain_run_id(match.group(2))
                else match.group(1) + hash_run_id(match.group(2))
            ),
            value,
        )
    if isinstance(value, dict):
        return {key: scrub_callback_credentials(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_callback_credentials(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_callback_credentials(item) for item in value)
    return value


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
