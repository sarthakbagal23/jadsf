"""Shared helper for integration modules: one tool-entry builder."""


def tool(name, description, properties, required, fn):
    return {
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        },
        "function": fn,
    }
