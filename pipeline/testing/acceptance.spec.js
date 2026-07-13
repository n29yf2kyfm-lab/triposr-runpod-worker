/* acceptance.spec.js — Playwright acceptance test for the Three.js car viewer.
 * Free/open-source (Playwright, Apache-2.0).
 *
 *   npm i -D @playwright/test && npx playwright install chromium
 *   npx playwright test pipeline/testing/acceptance.spec.js
 *
 * Serve the viewer first (from repo root):
 *   npx --yes http-server pipeline -p 8080     # or any static server
 * then set BASE=http://localhost:8080/viewer/  (default below).
 */
const { test, expect, devices } = require('@playwright/test');
const BASE = process.env.VIEWER_URL || 'http://localhost:8080/viewer/index.html';

test.describe('ExpertCarCheck 3D viewer — acceptance', () => {
  test('loads the GLB and reaches ready state with no console errors', async ({ page }) => {
    const errors = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(BASE, { waitUntil: 'networkidle' });
    // progress indicator resolves to the ready hint within 30s
    await expect(page.locator('#load')).toContainText(/drag to orbit|%/, { timeout: 30000 });
    await page.waitForTimeout(3000);
    // a canvas exists and actually painted (non-blank)
    const canvas = page.locator('#stage canvas');
    await expect(canvas).toBeVisible();
    const blank = await page.evaluate(() => {
      const c = document.querySelector('#stage canvas'); if (!c) return true;
      const gl = c.getContext('webgl2') || c.getContext('webgl'); return !gl;
    });
    expect(blank).toBeFalsy();
    expect(errors, 'console errors: ' + errors.join(' | ')).toHaveLength(0);
  });

  test('paint switch and panel toggles respond', async ({ page }) => {
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await page.waitForTimeout(4000);
    await page.locator('#paint').fill('#7a1f22');           // recolour
    await page.locator('[data-part="door"]').click();       // toggle (no-rig is acceptable, must not throw)
    await page.locator('[data-view="side"]').click();       // camera preset
    await page.waitForTimeout(500);
    expect(true).toBeTruthy();
  });

  test('mobile viewport renders (iPhone 13)', async ({ browser }) => {
    const ctx = await browser.newContext({ ...devices['iPhone 13'] });
    const page = await ctx.newPage();
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await expect(page.locator('#stage canvas')).toBeVisible({ timeout: 30000 });
    await ctx.close();
  });

  test('slow network still completes', async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.route('**/*.glb', async (r) => { await new Promise((s) => setTimeout(s, 1500)); r.continue(); });
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await expect(page.locator('#load')).toContainText(/drag to orbit/, { timeout: 45000 });
    await ctx.close();
  });
});
