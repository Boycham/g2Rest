# Floor Sense

Restaurant floor on Even Realities G2 glasses. See `AGENTS.md` for the brief.

## Frameworks and libraries

### Glasses app (`glasses/`)
- TypeScript (strict) + [Vite](https://vitejs.dev/): the Even Hub WebView app, scaffolded from
  [even-realities/evenhub-templates](https://github.com/even-realities/evenhub-templates) (`asr`)
- [@evenrealities/even_hub_sdk](https://www.npmjs.com/package/@evenrealities/even_hub_sdk) 0.0.16: G2 display, input and storage
- [@evenrealities/pretext](https://www.npmjs.com/package/@evenrealities/pretext): G2 font metrics for fitting card lines
- [@evenrealities/evenhub-simulator](https://www.npmjs.com/package/@evenrealities/evenhub-simulator) and
  [@evenrealities/evenhub-cli](https://www.npmjs.com/package/@evenrealities/evenhub-cli): simulator and `.ehpk` packing
- [vitest](https://vitest.dev/): tests
- [ws](https://www.npmjs.com/package/ws) and [tsx](https://www.npmjs.com/package/tsx): the dev-only fake backend
