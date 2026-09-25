import { defineConfig } from '@playwright/test'

// The web server runs the real FastAPI adapter against a disposable
// configuration in e2e/.tmp/, so end-to-end runs never touch the
// repository's real data/memory.json.
const PREPARE_CONFIG =
  'python3 -c "import json,os,shutil; os.makedirs(\'frontend/e2e/.tmp\',exist_ok=True); ' +
  'shutil.rmtree(\'frontend/e2e/.tmp/vault\', ignore_errors=True); ' +
  '[os.remove(p) for p in [\'frontend/e2e/.tmp/agentic.db\'] if os.path.exists(p)]; ' +
  'json.dump({\'agent_name\':\'Agentic OS\',\'version\':\'1.0.0\',' +
  '\'preferences\':{\'tone\':\'friendly\',\'language\':\'English\',\'save_history\':True},' +
  '\'memory_file\':\'frontend/e2e/.tmp/memory.json\',' +
  '\'database_file\':\'frontend/e2e/.tmp/agentic.db\',' +
  '\'vault_dir\':\'frontend/e2e/.tmp/vault\',\'maximum_history_items\':50,' +
  '\'stages\':[{\'path\':\'examples.stages.target_attainment.TargetAttainment\',' +
  '\'options\':{\'target\':3000000}}],' +
  '\'profiles\':{\'default\':[],\'with-target\':[\'target_attainment\']},' +
  '\'agent_runtime\':{\'path\':\'tests.test_agent_runtime.ScriptedRuntime\',' +
  '\'options\':{\'calls\':[[\'help\',{}]],\'closing\':\'Over to you.\',\'trigger\':\'sort out\'}}},' +
  'open(\'frontend/e2e/.tmp/config.json\',\'w\')); ' +
  'json.dump({},open(\'frontend/e2e/.tmp/memory.json\',\'w\'))"'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:8123',
    trace: 'retain-on-failure',
    // Use the environment's pre-installed Chromium when present instead of
    // downloading a browser (see PLAYWRIGHT_EXECUTABLE_PATH to override).
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH }
      : undefined,
  },
  projects: [
    {
      name: 'desktop',
      use: { viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'mobile',
      use: { viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true },
    },
  ],
  webServer: [
    {
      command: `${PREPARE_CONFIG} && python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8123`,
      cwd: '..',
      url: 'http://127.0.0.1:8123/api/health',
      env: { AGENTIC_OS_CONFIG: 'frontend/e2e/.tmp/config.json' },
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      // Second instance with managed auth enabled, for e2e/auth.spec.ts.
      // The secret is test-only and the provider is never contacted.
      command:
        'python3 -c "import json,os; os.makedirs(\'frontend/e2e/.tmp/auth\',exist_ok=True); ' +
        'json.dump({\'agent_name\':\'Agentic OS\',\'version\':\'1.0.0\',' +
        "'memory_file':'frontend/e2e/.tmp/auth/memory.json'," +
        "'database_file':'frontend/e2e/.tmp/auth/agentic.db'," +
        "'vault_dir':'frontend/e2e/.tmp/auth/vault'}, " +
        'open(\'frontend/e2e/.tmp/auth/config.json\',\'w\'))" ' +
        '&& python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8124',
      cwd: '..',
      url: 'http://127.0.0.1:8124/api/health',
      env: {
        AGENTIC_OS_CONFIG: 'frontend/e2e/.tmp/auth/config.json',
        AGENTIC_OS_JWT_SECRET: 'e2e-test-signing-secret',
        SUPABASE_URL: 'https://example.supabase.co',
        SUPABASE_ANON_KEY: 'e2e-publishable-key',
      },
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
})
