from __future__ import annotations

from typing import Any


class SchemaValidationError(ValueError):
    pass


_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def validate_json_schema(value: Any, schema: dict[str, Any] | None, *, path: str = "$") -> None:
    """Validate the JSON Schema subset used by ToolSpec contracts.

    The project deliberately keeps this dependency-free. Unsupported schema
    keywords are ignored, while type, required, properties, items, enum and
    additionalProperties are enforced.
    """

    if not schema:
        return
    expected = schema.get("type")
    if isinstance(expected, list):
        errors: list[str] = []
        for item in expected:
            try:
                validate_json_schema(value, {**schema, "type": item}, path=path)
                return
            except SchemaValidationError as exc:
                errors.append(str(exc))
        raise SchemaValidationError(f"{path} does not match any allowed type: {expected}")
    if expected:
        python_type = _TYPE_MAP.get(str(expected))
        if python_type is not None:
            if expected == "integer" and isinstance(value, bool):
                raise SchemaValidationError(f"{path} must be an integer")
            if expected == "number" and isinstance(value, bool):
                raise SchemaValidationError(f"{path} must be a number")
            if not isinstance(value, python_type):
                raise SchemaValidationError(f"{path} must be {expected}, got {type(value).__name__}")

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{path} must be one of {schema['enum']}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise SchemaValidationError(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        for key, child in value.items():
            if key in properties:
                validate_json_schema(child, properties[key], path=f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise SchemaValidationError(f"{path}.{key} is not allowed")

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            validate_json_schema(item, schema["items"], path=f"{path}[{index}]")
