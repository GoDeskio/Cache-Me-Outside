/* Cache Me Outside integration, version 1.0.0. No secrets live in this file. */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.CacheMeOutside = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  var VERSION = "1.0.0";

  function attach(opts) {
    if (!opts || !opts.api || !opts.token) throw new Error("api and token are required");
    var api = String(opts.api).replace(/\/$/, "");
    if (!/^https?:\/\//.test(api)) throw new Error("api must be http or https");
    var token = String(opts.token);

    function call(method, path, body) {
      return fetch(api + path, {
        method: method,
        headers: {"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        body: body ? JSON.stringify(body) : undefined
      }).then(function (response) {
        return response.json().then(function (payload) {
          if (!response.ok) throw new Error(payload.error || String(response.status));
          return payload;
        });
      });
    }

    return {
      version: VERSION,
      listDatabases: function () { return call("GET", "/v1/databases").then(function (b) { return b.databases; }); },
      createDatabase: function (name, limits) {
        return call("POST", "/v1/databases", Object.assign({name: name}, limits || {}));
      },
      rotatePassword: function (name) { return call("POST", "/v1/databases/" + name + "/rotate-password", {}); },
      deleteDatabase: function (name) { return call("DELETE", "/v1/databases/" + name); },
      scanKeys: function (name, match) {
        return call("GET", "/v1/databases/" + encodeURIComponent(name) + "/keys?match=" + encodeURIComponent(match || "*"));
      }
    };
  }

  return {attach: attach, version: VERSION};
});
