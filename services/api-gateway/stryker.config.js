/**
 * Stryker mutation testing configuration for the api-gateway.
 *
 * Install:  npm install --save-dev @stryker-mutator/core @stryker-mutator/jest-runner
 * Run:      npx stryker run
 *
 * @type {import('@stryker-mutator/api/core').PartialStrykerOptions}
 */
module.exports = {
  testRunner: 'jest',
  jest: {
    projectType: 'custom',
    config: require('./jest.config.js'),
    enableFindRelatedTests: true,
  },
  mutate: [
    'src/**/*.ts',
    '!src/app.ts',
    '!src/tracing.ts',
  ],
  thresholds: { high: 75, low: 60, break: 0 },
  reporters: ['html', 'progress', 'clear-text'],
  htmlReporter: { fileName: 'reports/mutation/mutation.html' },
  concurrency: 4,
  coverageAnalysis: 'perTest',
  ignoreStatic: true,
  disableTypeChecks: true,
};
