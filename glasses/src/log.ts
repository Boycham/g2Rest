/** Our own log lines, prefixed so they can be filtered out of the SDK's noise. */
export function log(...args: unknown[]): void {
  console.log('[fs]', ...args)
}
