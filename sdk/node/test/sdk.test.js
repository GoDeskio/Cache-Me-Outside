'use strict';
const test = require('node:test');
const assert = require('node:assert');
const cmo = require('..');

test('parse', () => {
  assert.deepStrictEqual(cmo.parseUrl('rediss://acme:p%40ss@cache.example:6380/2'),
    { host: 'cache.example', port: 6380, tls: true, username: 'acme', password: 'p@ss', db: 2 });
  const i = cmo.parseUrl('redis://:pw@h');
  assert.deepStrictEqual([i.username, i.password, i.port, i.tls], [undefined, 'pw', 6379, false]);
});

test('bad urls', () => {
  for (const u of ['http://h', 'nope', 'redis://h/x']) assert.throws(() => cmo.parseUrl(u));
});

test('options', () => {
  const o = cmo.glideOptions(cmo.parseUrl('rediss://u:p@h:1/3'));
  assert.deepStrictEqual(o, { addresses: [{ host: 'h', port: 1 }], useTLS: true, databaseId: 3,
    credentials: { username: 'u', password: 'p' } });
  assert.ok(!('credentials' in cmo.glideOptions(cmo.parseUrl('redis://h'))));
});

test('tenant prefixing', async () => {
  const log = [];
  const raw = { get: async (k) => log.push(['get', k]), set: async (k, v) => log.push(['set', k, v]),
    del: async (ks) => log.push(['del', ks]), close: async () => log.push(['close']) };
  const glide = { GlideClient: { createClient: async () => raw } };
  const c = await cmo.connect('redis://acme:p@h', { prefix: 'acme', glide });
  await c.set('a', '1'); await c.get('acme:a'); await c.del(['b']); await c.close();
  assert.deepStrictEqual(log, [['set', 'acme:a', '1'], ['get', 'acme:a'], ['del', ['acme:b']], ['close']]);
});

test('bad prefix', () => {
  for (const p of ['', 'a*', 'a b']) assert.throws(() => new cmo.TenantClient({}, p));
});
