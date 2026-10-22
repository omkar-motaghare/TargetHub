import { defineConfig } from '@playwright/test'

// Uses the system Chrome so no browser download (or sudo) is needed.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: process.env.TARGETHUB_URL || 'http://127.0.0.1:8000',
    channel: 'chrome',
    headless: true,
  },
})
