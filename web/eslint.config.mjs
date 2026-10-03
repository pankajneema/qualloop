import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

const config = [
  {
    ignores: [
      '.next/**',
      'node_modules/**',
      'coverage/**',
      'playwright-report/**',
      'next-env.d.ts',
    ],
  },
  ...nextVitals,
  ...nextTs,
  {
    // Design tokens live only in src/design/tokens.ts (ADR-013): no hex colour literals elsewhere.
    files: ['**/*.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: 'Literal[value=/#[0-9a-fA-F]{3,8}\\b/]',
          message: 'Hex colours belong in src/design/tokens.ts only.',
        },
      ],
    },
  },
  {
    files: ['src/design/tokens.ts', 'src/design/tokens.test.ts'],
    rules: { 'no-restricted-syntax': 'off' },
  },
];

export default config;
