import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const SCREENSHOTS_DIR = 'public/screenshots';
const BASE_URL = 'http://localhost:3000';

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    deviceScaleFactor: 2,
  });

  // Screenshot 1: Landing page (unauthenticated)
  console.log('Taking screenshot 1: Landing page...');
  const page1 = await context.newPage();
  await page1.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
  await page1.waitForTimeout(2000); // Wait for animations
  await page1.screenshot({ path: `${SCREENSHOTS_DIR}/01-landing.png` });
  await page1.close();

  // Screenshot 2: Terminal
  console.log('Taking screenshot 2: Terminal...');
  const page2 = await context.newPage();
  await page2.goto(`${BASE_URL}/terminal`, { waitUntil: 'networkidle', timeout: 30000 });
  await page2.waitForTimeout(3000); // Wait for chart to render
  await page2.screenshot({ path: `${SCREENSHOTS_DIR}/02-terminal.png` });
  await page2.close();

  // Screenshot 3: Dashboard
  console.log('Taking screenshot 3: Dashboard...');
  const page3 = await context.newPage();
  await page3.goto(`${BASE_URL}/terminal/dashboard`, { waitUntil: 'networkidle', timeout: 30000 });
  await page3.waitForTimeout(2000);
  await page3.screenshot({ path: `${SCREENSHOTS_DIR}/03-dashboard.png` });
  await page3.close();

  await browser.close();
  console.log('All screenshots saved to public/screenshots/');
}

main().catch(console.error);
