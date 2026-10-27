import { defineConfig } from '@playwright/test'

// Defaults to the system Chrome so no browser download (or sudo) is needed.
// Override with PLAYWRIGHT_CHANNEL=chromium or PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: process.env.TARGETHUB_URL || 'http://127.0.0.1:8000',
    channel: executablePath ? undefined : process.env.PLAYWRIGHT_CHANNEL || 'chrome',
    launchOptions: executablePath ? { executablePath } : undefined,
    headless: true,
  },
})
