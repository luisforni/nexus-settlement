/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  testMatch: ['**/tests/**/*.test.ts'],
  setupFiles: ['./tests/setup.ts'],
  collectCoverageFrom: ['src/**/*.ts', '!src/app.ts'],
  coverageThreshold: { global: { branches: 70, functions: 80, lines: 80, statements: 80 } },
  moduleNameMapper: {
    // Strip .js extensions for Jest module resolution (ESM compat)
    '^(\\./.*)\\.js$': '$1',
    '^(\\.\\./.*)\\.js$': '$1',
  },
};
