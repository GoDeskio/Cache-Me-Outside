# Cache Me Outside MCP server

Lets AI agents (Claude Desktop, Cursor, any MCP client) read and, if allowed, write a Cache Me Outside database. Pure Python 3, no dependencies.

```json
{ "mcpServers": { "cache-me-outside": {
  "command": "python3", "args": ["/path/to/tools/mcp/cmo_mcp.py"],
  "env": { "CMO_MCP_URL": "rediss://agent:PASSWORD@cache.example.com:6379/0" } } } }
```

Tools: `cache_get`, `cache_ttl`, `cache_scan`, `cache_stats`; with `CMO_MCP_WRITE=1` also `cache_set` (64 KB max, optional TTL) and `cache_delete`.

Give each agent its own ACL user or a read-only, prefix-scoped API key (`deploy/api-key.sh create --scope ro --prefix agent: --ttl-days 30`), never the admin password. Test: `python3 tools/mcp/test_cmo_mcp.py`.
API keys arrive with PR #7.
