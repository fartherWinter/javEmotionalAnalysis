"""Test-only stdio server; no real database or secrets."""
from mcp.server.fastmcp import FastMCP
from typing import Any

server = FastMCP("fixture")


@server.tool()
def health_check() -> dict[str, Any]:
    return {"ok": True}


@server.tool()
def get_status() -> dict[str, Any]:
    return {"config": {"dbReady": True, "wxid": "fixture-account"}, "status": {"connection": {"ok": True}}}


@server.tool()
def list_sessions(type: str, limit: int, offset: int) -> dict[str, Any]:
    return {"items": [{"sessionId": "fixture-session", "displayName": "测试会话", "type": type}], "hasMore": False}


@server.tool()
def get_messages(sessionId: str, limit: int, cursor: str | None = None) -> dict[str, Any]:
    return {"items": [{"localId": 2 if cursor else 1, "type": 1, "content": "第二页" if cursor else "第一页", "direction": "in"}], "cursor": None if cursor else "next"}


@server.tool()
def list_contacts(limit: int) -> dict[str, Any]:
    return {"items": [{"wxid": "fixture-session", "displayName": "联系人昵称"}]}


if __name__ == "__main__":
    server.run(transport="stdio")
