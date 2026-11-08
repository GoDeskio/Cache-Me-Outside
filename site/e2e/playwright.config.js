const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: ".",
  timeout: 30000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8091",
    ...(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {}),
  },
  webServer: {
    command: "python3 ../server.py --demo --listen 127.0.0.1:8091",
    url: "http://127.0.0.1:8091/",
    reuseExistingServer: false,
    timeout: 20000,
  },
});
