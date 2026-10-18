// Links between the Verity pages and the existing kitchen page, carrying ?api so every page
// talks to the same backend. The token never rides in a link: client.js keeps it in sessionStorage.
const api = new URLSearchParams(location.search).get('api')

function withApi(path: string): string {
  if (!api) return path
  const url = new URL(path, location.href)
  url.searchParams.set('api', api)
  return url.href
}

// Built, the pages sit in web/verity/dist/ next to web/kitchen.html; in dev they run on Vite
// while web/ is served on its own port (NOTES.md), so VITE_WEB_URL can point there.
const webRoot: string = import.meta.env.VITE_WEB_URL ?? (import.meta.env.DEV ? 'http://localhost:5173/' : '../../')

export const links = {
  story: withApi('./index.html'),
  dashboard: withApi('./dashboard.html'),
  kitchen: withApi(new URL('kitchen.html', new URL(webRoot, location.href)).href),
  organizer: withApi(new URL('index.html', new URL(webRoot, location.href)).href),
}
