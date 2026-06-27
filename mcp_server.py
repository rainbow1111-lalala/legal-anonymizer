#!/usr/bin/env python3
"""
Legal Document Anonymizer - MCP Server

Provides redaction services over the MCP (Model Context Protocol).
All data is processed locally and never uploaded to the cloud.

Configuration - add the following to ~/.claude/settings.json:
{
  "mcpServers": {
    "legal-anonymizer": {
      "command": "python3",
      "args": ["/path/to/legal-anonymizer/mcp_server.py"]
    }
  }
}
"""

import sys
import json
import asyncio
from pathlib import Path
from typing import Any

# Make sure the module path is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

from anonymizer import LegalAnonymizer

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


def create_mcp_server():
    """Create the MCP server."""
    if not HAS_MCP:
        raise ImportError("The MCP SDK is required: pip install mcp")

    server = Server("legal-anonymizer-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="anonymize_file",
                description="Redact a file. Supports PDF, Word (.doc/.docx), images, and plain text. Automatically detects sensitive information such as person names, company names, ID numbers, and mobile numbers. All data is processed locally.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "input_path": {
                            "type": "string",
                            "description": "Input file path"
                        },
                        "output_path": {
                            "type": "string",
                            "description": "Output file path (optional; defaults to the same directory)"
                        },
                        "entities": {
                            "type": "string",
                            "description": "Custom entities as a JSON string, e.g. [{\"type\":\"person\",\"name\":\"张三\"}] (optional)"
                        },
                        "entities_path": {
                            "type": "string",
                            "description": "Path to a custom-entities JSON file (optional)"
                        },
                        "output_format": {
                            "type": "string",
                            "description": "Output format",
                            "enum": ["auto", "txt", "pdf", "docx", "md"],
                            "default": "auto"
                        },
                        "only_types": {
                            "type": "string",
                            "description": "Redact only the listed types, comma-separated (optional)"
                        },
                        "exclude_types": {
                            "type": "string",
                            "description": "Exclude the listed types, comma-separated (optional)"
                        },
                        "mask_strategy": {
                            "type": "string",
                            "description": "Mask strategy: placeholder or partial (partial masking)",
                            "enum": ["placeholder", "partial"],
                            "default": "placeholder"
                        },
                        "use_ocr": {
                            "type": "boolean",
                            "description": "Use OCR for PDFs (handles scanned documents)",
                            "default": False
                        }
                    },
                    "required": ["input_path"]
                }
            ),
            Tool(
                name="anonymize_text",
                description="Redact text content. Runs redaction directly on text and automatically detects sensitive information.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The text content to redact"
                        },
                        "entities": {
                            "type": "string",
                            "description": "Custom entities as a JSON string (optional)"
                        },
                        "only_types": {
                            "type": "string",
                            "description": "Redact only the listed types, comma-separated (optional)"
                        },
                        "exclude_types": {
                            "type": "string",
                            "description": "Exclude the listed types, comma-separated (optional)"
                        },
                        "mask_strategy": {
                            "type": "string",
                            "description": "Mask strategy",
                            "enum": ["placeholder", "partial"]
                        }
                    },
                    "required": ["text"]
                }
            ),
            Tool(
                name="analyze_document",
                description="Analyze a document for sensitive information. Detects sensitive information in the document without actually redacting it.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "input_path": {
                            "type": "string",
                            "description": "Input file path"
                        },
                        "only_types": {
                            "type": "string",
                            "description": "Analyze only the listed types, comma-separated (optional)"
                        },
                        "exclude_types": {
                            "type": "string",
                            "description": "Exclude the listed types, comma-separated (optional)"
                        }
                    },
                    "required": ["input_path"]
                }
            ),
            Tool(
                name="list_supported_types",
                description="List all supported sensitive-information types.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: Any) -> list[TextContent]:
        # Create a new instance per call to avoid state leakage
        anonymizer = LegalAnonymizer()

        try:
            if name == "anonymize_file":
                return await _handle_anonymize_file(anonymizer, arguments)
            elif name == "anonymize_text":
                return await _handle_anonymize_text(anonymizer, arguments)
            elif name == "analyze_document":
                return await _handle_analyze_document(anonymizer, arguments)
            elif name == "list_supported_types":
                return await _handle_list_types(anonymizer)
            else:
                return [TextContent(type="text", text=json.dumps(
                    {"error": f"Unknown tool: {name}"}, ensure_ascii=False
                ))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps(
                {"error": str(e)}, ensure_ascii=False
            ))]

    async def _handle_anonymize_file(anonymizer: LegalAnonymizer, args: dict) -> list[TextContent]:
        input_path = args["input_path"]
        output_path = args.get("output_path")
        output_format = args.get("output_format", "auto")
        use_ocr = args.get("use_ocr", False)

        # Load custom entities
        custom_entities = _parse_entities(args)

        # Parse the type filters
        only_types = args.get("only_types", "").split(",") if args.get("only_types") else None
        exclude_types = args.get("exclude_types", "").split(",") if args.get("exclude_types") else None

        # Set the mask strategy
        if args.get("mask_strategy"):
            anonymizer.set_all_mask_strategy(args["mask_strategy"])

        result = anonymizer.anonymize_file(
            input_path, output_path,
            custom_entities=custom_entities,
            output_format=output_format,
            only_types=only_types,
            exclude_types=exclude_types,
            use_ocr=use_ocr
        )

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    async def _handle_anonymize_text(anonymizer: LegalAnonymizer, args: dict) -> list[TextContent]:
        text = args["text"]

        custom_entities = _parse_entities(args)
        if custom_entities:
            anonymizer.add_custom_entities(custom_entities)

        only_types = args.get("only_types", "").split(",") if args.get("only_types") else None
        exclude_types = args.get("exclude_types", "").split(",") if args.get("exclude_types") else None

        if args.get("mask_strategy"):
            anonymizer.set_all_mask_strategy(args["mask_strategy"])

        anonymized_text, mapping = anonymizer.anonymize_text(text, only_types, exclude_types)

        result = {
            "action": "anonymize_text",
            "status": "success",
            "result": {
                "anonymized_text": anonymized_text,
                "mapping": mapping["mapping"],
                "total_matched": mapping["metadata"]["entity_count"],
                "replacements_made": mapping["metadata"]["replacements_made"],
            }
        }

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    async def _handle_analyze_document(anonymizer: LegalAnonymizer, args: dict) -> list[TextContent]:
        input_path = args["input_path"]

        only_types = args.get("only_types", "").split(",") if args.get("only_types") else None
        exclude_types = args.get("exclude_types", "").split(",") if args.get("exclude_types") else None

        result = anonymizer.analyze_file(input_path, only_types, exclude_types)

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    async def _handle_list_types(anonymizer: LegalAnonymizer) -> list[TextContent]:
        types = anonymizer.get_supported_types()

        # Add the types covered by automatic detection
        auto_types = {
            'person': 'Person name (auto-detected)',
            'company': 'Company (auto-detected)',
            'law_firm': 'Law firm (auto-detected)',
            'court': 'Court (auto-detected)',
            'government': 'Government (auto-detected)',
            'institution': 'Institution (auto-detected)',
            'bank_name': 'Bank (auto-detected)',
        }
        types.update(auto_types)

        result = {
            "action": "list_supported_types",
            "status": "success",
            "result": {
                "types": types,
                "count": len(types)
            }
        }

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    def _parse_entities(args: dict):
        """Parse the custom-entities argument."""
        entities_str = args.get("entities")
        entities_path = args.get("entities_path")

        if entities_path:
            path = Path(entities_path)
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        elif entities_str:
            return json.loads(entities_str)

        return None

    return server


async def main():
    server = create_mcp_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    if not HAS_MCP:
        print("Error: the MCP SDK is required", file=sys.stderr)
        print("Install with: pip install mcp", file=sys.stderr)
        sys.exit(1)

    asyncio.run(main())
