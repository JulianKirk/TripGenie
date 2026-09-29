"""Validate wire schemas without allowing implicit network retrieval."""

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .errors import validation_error


def validate_schema(schema: dict[str, Any]) -> None:
    def check(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(item, str) or not item.startswith("#")
                ):
                    raise validation_error(
                        "Only local JSON schema references are supported."
                    )
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise validation_error("Invalid JSON schema.") from exc
