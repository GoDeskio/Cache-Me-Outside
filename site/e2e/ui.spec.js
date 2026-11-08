const { test, expect } = require("@playwright/test");
const fs = require("fs");

fs.mkdirSync("screenshots", { recursive: true });

test("home, console, flow, and integrate", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.locator("#hero h1")).toHaveText("The cache that stays on your desk.");
  await page.screenshot({ path: "screenshots/home-1440.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "screenshots/home-390.png" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.getByRole("link", { name: "GitGoat" })).toHaveAttribute("href", "https://gitgoat.io");
  await expect(page.getByRole("link", { name: "RailYard" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Portkyl" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Komboe" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Cerebro" })).toBeVisible();
  await page.mouse.move(180, 120);
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--mx").trim())).toBe("180px");
  await page.getByRole("button", { name: "Explain tenants" }).click();
  await expect(page.locator("#agent-out")).toContainText("password");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Menu" }).click();
  await expect(page.locator("#nav")).toBeVisible();
  await page.locator("#nav").getByRole("link", { name: "Console", exact: true }).click();

  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.locator("#demo-banner")).toBeVisible();
  await page.locator("#name").fill("A");
  await page.getByRole("button", { name: "Create database" }).click();
  await expect(page.locator("#err")).toContainText("Name");
  await page.locator("#name").fill("acme");
  await page.getByRole("button", { name: "Create database" }).click();
  await expect(page.locator("#result")).toContainText("shown once");
  await expect(page.locator("#result .url")).toHaveValue(/redis:\/\/acme:/);
  await page.getByRole("button", { name: "Copy URL" }).click();
  await expect(page.locator("#dbs")).toContainText("acme");
  await expect(page.locator("#dbs")).toContainText("unlimited");

  await page.getByRole("button", { name: "Browse" }).click();
  await page.getByRole("button", { name: "acme:welcome" }).click();
  await page.getByRole("button", { name: "Show value" }).click();
  await expect(page.locator("#kv")).toContainText("hello from Cache Me Outside");
  await page.getByRole("button", { name: "Hide value" }).click();
  await expect(page.locator("#kv pre")).toHaveText("hidden");
  await page.locator("#bmatch").fill("nope*");
  await page.getByRole("button", { name: "Search keys" }).click();
  await expect(page.locator("#keys")).toContainText("No keys match.");
  await page.locator("#bmatch").fill("*");
  await page.getByRole("button", { name: "Search keys" }).click();
  await expect(page.locator("#keys")).toContainText("acme:welcome");

  await page.getByRole("button", { name: "Limits" }).click();
  await page.locator("#lim-ops").fill("25");
  await page.getByRole("button", { name: "Save limits" }).click();
  await expect(page.locator("#dbs")).toContainText("ops/s 25");
  await page.getByRole("button", { name: "New password" }).click();
  await expect(page.locator("#result")).toContainText("shown once");
  await page.getByRole("button", { name: "List databases" }).click();
  await expect(page.locator("#agent-out")).toContainText("acme");
  await page.locator("#agent-q").fill("create database beta");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.locator("#dbs")).toContainText("beta");
  await page.getByRole("button", { name: "Create demo" }).click();
  await expect(page.locator("#dbs")).toContainText("demo");
  await page.locator("article", { hasText: "acme" }).getByRole("button", { name: "Delete" }).click();
  await expect(page.locator("#dbs")).not.toContainText("Port 7001");
  await page.evaluate(() => {
    document.getElementById("result").hidden = true;
    document.getElementById("agent-out").textContent = "";
  });
  await page.locator("#dbs").scrollIntoViewIfNeeded();
  await page.screenshot({ path: "screenshots/console-1440.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "screenshots/console-390.png" });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator("#agent-q").fill("open flow");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page).toHaveURL(/\/flow$/);
  await expect(page.locator("#flow-note")).toBeVisible();
  await expect(page.locator("#stats")).toContainText("req/s");
  await expect.poll(() => page.locator("#dots circle").count()).toBeGreaterThan(0);
  await page.screenshot({ path: "screenshots/flow-1440.png" });

  await page.getByRole("link", { name: "Integrate" }).click();
  await page.getByRole("button", { name: "Show version" }).click();
  await expect(page.locator("#version-out")).toHaveText("cache-me-outside 1.0.0 (api v1)");
  await page.getByRole("button", { name: "Explain integration" }).click();
  await expect(page.locator("#agent-out")).toContainText("environment");
  expect(errors).toEqual([]);
});

test("reduced motion keeps the flow still", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await page.goto("/flow");
  await page.mouse.move(40, 40);
  await page.waitForTimeout(900);
  await expect(page.locator("#dots circle")).toHaveCount(0);
  await expect(page.locator("#stats")).toContainText("req/s");
  const mx = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--mx").trim());
  expect(mx).not.toBe("40px");
  await page.screenshot({ path: "screenshots/flow-390.png" });
  await context.close();
});
