"""The app's MCP server: lets an AI agent list, check, book and cancel treks.

routes/mcp_routes.py is the HTTP door (token, Origin, size). protocol.py speaks
JSON-RPC and MCP, tools.py holds the five tools, visits.py the throwaway
trekkers, housekeeping and limits, and schema.py checks tool arguments.
The package isn't called `mcp`, which would shadow the official SDK's name.
See docs/MCP.md for the design and its trade-offs.
"""
