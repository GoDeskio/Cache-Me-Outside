// Cache Me Outside Node SDK: thin wrapper over @valkey/valkey-glide.
// Parses a CMO URL into Glide options and keeps keys inside the tenant prefix.
'use strict';

const SCHEMES = { 'redis:': false, 'rediss:': true, 'valkey:': false, 'valkeys:': true };

function parseUrl(url) {
  let u;
  try { u = new URL(url); } catch { throw new Error('invalid url'); }
  if (!(u.protocol in SCHEMES)) throw new Error(`unsupported scheme: ${u.protocol}`);
  if (!u.hostname) throw new Error('missing host');
  const path = u.pathname.replace(/^\/+|\/+$/g, '');
  if (path && !/^\d+$/.test(path)) throw new Error('db must be a number');
  return {
    host: u.hostname,
    port: u.port ? Number(u.port) : 6379,
    tls: SCHEMES[u.protocol],
    username: u.username ? decodeURIComponent(u.username) : undefined,
    password: u.password ? decodeURIComponent(u.password) : undefined,
    db: path ? Number(path) : 0,
  };
}

function glideOptions(info) {
  const o = { addresses: [{ host: info.host, port: info.port }], useTLS: info.tls, databaseId: info.db };
  if (info.password !== undefined) o.credentials = { username: info.username, password: info.password };
  return o;
}

class TenantClient {
  constructor(client, prefix) {
    if (!prefix || /[*?\[\] ]/.test(prefix)) throw new Error('invalid prefix');
    this.raw = client;
    this.prefix = prefix.endsWith(':') ? prefix : prefix + ':';
  }
  key(k) { return k.startsWith(this.prefix) ? k : this.prefix + k; }
  get(k) { return this.raw.get(this.key(k)); }
  set(k, v, opts) { return this.raw.set(this.key(k), v, opts); }
  del(keys) { return this.raw.del(keys.map((k) => this.key(k))); }
  exists(keys) { return this.raw.exists(keys.map((k) => this.key(k))); }
  incr(k) { return this.raw.incr(this.key(k)); }
  expire(k, s) { return this.raw.expire(this.key(k), s); }
  close() { return this.raw.close(); }
}

async function connect(url, { prefix, glide } = {}) {
  const g = glide || require('@valkey/valkey-glide');
  const client = await g.GlideClient.createClient(glideOptions(parseUrl(url)));
  return prefix ? new TenantClient(client, prefix) : client;
}

module.exports = { parseUrl, glideOptions, TenantClient, connect };
