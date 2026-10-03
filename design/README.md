# design/

Home for design-canvas exports and screenshots (PNG/SVG/PDF) used as visual references while building screens.

- The source of truth for look and feel is `docs/design/DESIGN_SPEC.md`, not the files here.
- Tokens are implemented in `web/src/design/tokens.ts`; never copy values from an image into code.
- Keep files small (the pre-commit hook rejects files over 500 kB); link to the canvas for anything larger.
- Do not store real customer data or real supplier names in screenshots.
