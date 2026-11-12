from __future__ import annotations

from typing import Any, TextIO

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses duplicate explicit mapping keys."""

    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            # A YAML merge intentionally supplies defaults that an explicit
            # key may override. Only duplicate keys written in this mapping
            # are ambiguous and must fail.
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
            except TypeError as error:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable mapping key",
                    key_node.start_mark,
                ) from error
            if duplicate:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def safe_load_unique(stream: str | TextIO) -> Any:
    """Load trusted-shape YAML safely while rejecting duplicate keys."""
    # UniqueKeySafeLoader extends yaml.SafeLoader; yaml.load is required to
    # install the duplicate-key constructor rather than the stock safe loader.
    return yaml.load(stream, Loader=UniqueKeySafeLoader)  # nosec B506
