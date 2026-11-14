import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

const securityHeaders = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'X-Frame-Options': 'DENY',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}

/** Production builds get a strict Content-Security-Policy. The dev server needs inline scripts for hot reload, so it skips it. */
function csp(apiOrigin: string): Plugin {
  return {
    name: 'f1-csp',
    apply: 'build',
    transformIndexHtml(html) {
      const policy = `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'${apiOrigin ? ' ' + apiOrigin : ''}; base-uri 'none'; form-action 'none'; object-src 'none'`
      return html.replace('<meta name="referrer"', `<meta http-equiv="Content-Security-Policy" content="${policy}" />\n    <meta name="referrer"`)
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const api = (env.VITE_API_URL || '').replace(/\/$/, '')
  const target = `http://127.0.0.1:${process.env.API_PORT || 8010}`
  return {
    plugins: [react(), csp(api)],
    server: { host: '127.0.0.1', headers: securityHeaders, proxy: { '/api': target, '/health': target } },
    preview: { host: '127.0.0.1', headers: securityHeaders },
  }
})
