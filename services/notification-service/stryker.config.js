/**
 * Stryker mutation testing configuration for the notification-service.
 *
 * Install:  npm install --save-dev @stryker-mutator/core @stryker-mutator/jest-runner
 * Run:      npx stryker run
 * Report:   open reports/mutation/mutation.html
 *
 * Stryker docs: https://stryker-mutator.io/docs/stryker-js/configuration/
 *
 * @type {import('@stryker-mutator/api/core').PartialStrykerOptions}
 */
module.exports = {
  // ── Test runner ────────────────────────────────────────────────────────────
  testRunner: 'jest',
  jest: {
    projectType: 'custom',
    config: require('./jest.config.js'),
    enableFindRelatedTests: true,  // Run only tests related to mutated source files
  },

  // ── Files to mutate ────────────────────────────────────────────────────────
  // Focus on business logic; exclude app bootstrap and tracing boilerplate
  mutate: [
    'src/**/*.ts',
    '!src/app.ts',          // Bootstrap / side-effect code — not meaningful to mutate
    '!src/tracing.ts',      // OTel init — not meaningful to mutate
    '!src/logger.ts',       // Logger factory — not meaningful to mutate
    '!src/config.ts',       // Zod schema parsing — low ROI for mutation testing
  ],

  // ── Mutation thresholds ────────────────────────────────────────────────────
  // break:0 prevents CI failures on first Stryker run while we ramp up coverage.
  // Raise these thresholds once mutation scores are established.
  thresholds: {
    high: 75,     // Green  — mutation score above this value
    low: 60,      // Yellow — mutation score between low and high
    break: 0,     // Red    — scores below this value fail the build
  },

  // ── Report formats ─────────────────────────────────────────────────────────
  reporters: ['html', 'progress', 'clear-text'],
  htmlReporter: {
    fileName: 'reports/mutation/mutation.html',
  },

  // ── Performance ───────────────────────────────────────────────────────────
  concurrency: 4,        // Parallel test workers
  coverageAnalysis: 'perTest',  // Only test mutants covered by failing tests

  // ── Ignore patterns ────────────────────────────────────────────────────────
  // Don't mutate import statements, type assertions, or log messages
  ignoreStatic: true,
  disableTypeChecks: true,   // Speed up runs; type errors caught by tsc separately
};
