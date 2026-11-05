# cachemeoutside (Python)

A thin wrapper over [valkey-glide](https://github.com/valkey-io/valkey-glide).

```python
import asyncio, cachemeoutside as cmo
async def main():
    c = await cmo.connect("rediss://acme:SECRET@cache.example:6380", prefix="acme")
    await c.set("greeting", "hi")      # stored as acme:greeting
    print(await c.get("greeting"))
    await c.close()
asyncio.run(main())
```

- `prefix` keeps keys inside the tenant ACL (`~acme:*`). `c.raw` is the plain Glide client.
- Tests run offline with a fake Glide module: `python3 -m unittest discover -s sdk/python/tests`.
- Status: not yet tested against a live server. The Node and Go SDKs are follow-ups.
