# @cachemeoutside/client (Node)

A thin wrapper over `@valkey/valkey-glide`, which you install alongside it.

```js
const cmo = require('@cachemeoutside/client');
const c = await cmo.connect('rediss://acme:SECRET@cache.example:6380', { prefix: 'acme' });
await c.set('greeting', 'hi'); // stored as acme:greeting
```

- `prefix` keeps keys inside the tenant ACL. `c.raw` is the plain Glide client.
- Run the tests with `npm test`. They run offline with a fake Glide object.
- Status: not yet tested against a live server, and not published.
