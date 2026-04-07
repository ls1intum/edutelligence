"""
OpenAI-backed implementation of AbstractLanguageModel.
Supports both OpenAI and Azure OpenAI clients.
Includes a LangChain ChatOpenAI adapter via `langchain_openai`.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union, cast

from langchain_openai import AzureChatOpenAI, ChatOpenAI
from openai import AzureOpenAI, Omit, OpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
)
from openai.types.shared_params.response_format_json_schema import (
    JSONSchema,
    ResponseFormatJSONSchema,
)

from memiris.llm.abstract_language_model import (
    AbstractLanguageModel,
    WrappedChatResponse,
    WrappedEmbeddingResponse,
)


class OpenAiLanguageModel(AbstractLanguageModel):
    """Concrete language model adapter using OpenAI and Azure OpenAI."""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        azure: bool = False,
        azure_endpoint: Optional[str] = None,
        api_version: Optional[str] = None,
    ) -> None:
        self._model = model
        self._azure = azure
        self._api_key = (
            api_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("AZURE_OPENAI_API_KEY")
        )
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self._azure_endpoint = azure_endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT")
        self._api_version = (
            api_version
            or os.environ.get("AZURE_OPENAI_API_VERSION")
            or "2025-04-01-preview"
        )
        self._client: OpenAI
        if azure:
            if not self._azure_endpoint:
                raise ValueError("Azure endpoint must be provided for Azure OpenAI.")
            self._client = AzureOpenAI(
                api_key=self._api_key,
                azure_endpoint=str(self._azure_endpoint),
                api_version=self._api_version,
            )
        else:
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)

    @property
    def model(self) -> str:
        return self._model

    def chat(
        self,
        messages: Sequence[Union[Mapping[str, Any], Any]],
        response_format: Optional[Dict[str, Any]] = None,
        keep_alive: Optional[Union[str, int]] = None,
        options: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> WrappedChatResponse:
        # normalize messages
        normalized: List[ChatCompletionMessageParam] = []
        for m in messages:
            if hasattr(m, "role") and hasattr(m, "content"):
                normalized.append(
                    cast(
                        ChatCompletionMessageParam,
                        {
                            "role": getattr(m, "role"),
                            "content": getattr(m, "content"),
                        },
                    )
                )
            elif isinstance(m, Mapping):
                d: Dict[str, Any] = {
                    "role": cast(str, m.get("role", "user")),
                    "content": m.get("content", ""),
                }
                if m.get("name") is not None:
                    d["name"] = m["name"]
                normalized.append(cast(ChatCompletionMessageParam, d))

        # build ResponseFormatJSONSchema; accept raw Pydantic schema or wrapped
        rf: Optional[ResponseFormatJSONSchema] = None
        unwrap_key: Optional[str] = (
            None  # if we wrap non-object roots, remember key to unwrap later
        )
        if response_format:
            raw = cast(
                Dict[str, Any],
                response_format.get("json_schema")
                or response_format.get("schema")
                or response_format,
            )

            root_key = cast(str, response_format.get("root_key", "result"))
            name = cast(str, raw.get("name") or raw.get("title") or "schema")

            schema_dict = cast(Dict[str, Any], raw.get("schema", raw)).copy()
            schema_dict.pop("$schema", None)  # remove draft URL

            defs = schema_dict.get("$defs") or schema_dict.get("definitions")
            top_type = cast(Optional[str], schema_dict.get("type"))

            if top_type != "object":
                # wrap non-object root and hoist $defs so internal $ref resolve
                inner = schema_dict.copy()
                inner.pop("$defs", None)
                inner.pop("definitions", None)
                wrapped: Dict[str, Any] = {
                    "type": "object",
                    "properties": {root_key: inner},
                    "required": [root_key],
                    "additionalProperties": False,
                }
                if defs:
                    wrapped["$defs"] = defs
                schema_dict = wrapped
                unwrap_key = root_key  # we will unwrap this key from the model output

            # enforce additionalProperties: false and all properties required (API requirement)
            def _enforce_strict_schema(s: Any) -> None:
                if not isinstance(s, dict):
                    return

                # If this schema has a $ref, remove all other keywords (OpenAI strict mode requirement)
                if "$ref" in s:
                    ref_value = s["$ref"]
                    s.clear()
                    s["$ref"] = ref_value
                    return

                t = s.get("type")
                if t == "object":
                    s["additionalProperties"] = False
                    # Ensure all properties are in the required array
                    props = s.get("properties")
                    if isinstance(props, dict):
                        # Add all property keys to required array
                        existing_required = s.get("required", [])
                        if not isinstance(existing_required, list):
                            existing_required = []
                        all_prop_keys = list(props.keys())
                        # Merge existing required with all properties, removing duplicates
                        s["required"] = list(set(existing_required + all_prop_keys))
                        # Recursively process nested properties
                        for v in props.values():
                            _enforce_strict_schema(v)
                    pprops = s.get("patternProperties")
                    if isinstance(pprops, dict):
                        for v in pprops.values():
                            _enforce_strict_schema(v)
                if t == "array":
                    _enforce_strict_schema(s.get("items"))
                for key in ("allOf", "anyOf", "oneOf"):
                    arr = s.get(key)
                    if isinstance(arr, list):
                        for sub in arr:
                            _enforce_strict_schema(sub)
                for defs_key in ("$defs", "definitions"):
                    dct = s.get(defs_key)
                    if isinstance(dct, dict):
                        for v in dct.values():
                            _enforce_strict_schema(v)

            _enforce_strict_schema(schema_dict)

            rf = ResponseFormatJSONSchema(
                type="json_schema",
                json_schema=JSONSchema(
                    name=name,
                    schema=schema_dict,
                    strict=True,
                ),
            )

        # merge options/kwargs, drop None
        payload: Dict[str, Any] = {}
        if options:
            payload.update({k: v for k, v in options.items() if k != "temperature"})
            if options.get("temperature") is not None and not self._model.startswith(
                "gpt-5"
            ):
                payload["temperature"] = options["temperature"]
        if kwargs:
            payload.update(kwargs)
        payload = {k: v for k, v in payload.items() if v is not None}

        resp: ChatCompletion = self._client.chat.completions.create(
            model=self._model,
            messages=normalized,
            response_format=rf or Omit(),
            **payload,
        )

        # If we wrapped a non-object schema, unwrap the key so downstream parsers
        # expecting a top-level array/object see exactly that.
        if unwrap_key:
            try:
                content = resp.choices[0].message.content or ""
                data = json.loads(content)
                if isinstance(data, dict) and unwrap_key in data:
                    inner = data[unwrap_key]
                    new_content = json.dumps(inner)
                    # Rebuild nested Pydantic models immutably
                    first = resp.choices[0]
                    new_message = first.message.model_copy(
                        update={"content": new_content}
                    )
                    new_choice = first.model_copy(update={"message": new_message})
                    new_choices = [new_choice] + list(resp.choices[1:])
                    resp = resp.model_copy(update={"choices": new_choices})
            except (ValueError, json.JSONDecodeError, AttributeError, TypeError) as exc:
                logging.getLogger(__name__).debug("OpenAI unwrap failed: %s", exc)

        return WrappedChatResponse.from_openai_chat(resp)

    def embed(self, text: str) -> WrappedEmbeddingResponse:
        resp = self._client.embeddings.create(model=self._model, input=text)
        return WrappedEmbeddingResponse.from_openai_embedding(resp)

    def langchain_client(self) -> Union[ChatOpenAI, AzureChatOpenAI]:
        if self._azure:
            return AzureChatOpenAI(
                model=self._model,
                api_key=self._api_key,  # type: ignore
                azure_endpoint=self._azure_endpoint,
                api_version=self._api_version,
            )
        return ChatOpenAI(
            model=self._model,
            api_key=self._api_key,  # type: ignore
            base_url=self._base_url,
        )

    def ensure_present(self) -> None:
        pass

    def is_loaded(self) -> bool:
        return True

    def load(self, duration: str = "5m") -> None:
        pass

    def unload(self) -> None:
        pass
