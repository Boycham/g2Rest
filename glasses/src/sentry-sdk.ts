// The only parts of @sentry/browser the glasses use. telemetry.ts imports this file lazily, so the
// SDK is its own chunk, tree-shaken to these names, and only loaded when /config has a DSN.
export {
  addBreadcrumb,
  breadcrumbsIntegration,
  continueTrace,
  flush,
  init,
  logger,
  setTags,
  startInactiveSpan,
  startNewTrace,
  withActiveSpan,
} from '@sentry/browser'
export type { BrowserOptions, Span } from '@sentry/browser'
