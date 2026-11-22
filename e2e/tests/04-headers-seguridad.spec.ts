import { expect, test, type APIResponse } from '@playwright/test';

/**
 * Flow 4 (TEST-09, note 3 of the security cross map, OPT-06):
 * Nginx drops every server-level `add_header` in a location that declares its
 * own, so the security headers are checked on each kind of location: the SPA
 * (`/` and a client-side route), a hashed asset (`/assets/…`) and the proxied
 * API (`/api/health`).
 */
const EXPECTED: Record<string, string> = {
  'x-content-type-options': 'nosniff',
  'x-frame-options': 'DENY',
  'referrer-policy': 'strict-origin-when-cross-origin',
};

/** CSP directives that must survive in every location (SEG-H15 added frame-ancestors). */
const CSP_DIRECTIVES: string[] = ["default-src 'self'", "script-src 'self'", "frame-ancestors 'none'"];

function expectSecurityHeaders(response: APIResponse): void {
  const all = response.headersArray();
  const values = (name: string): string[] =>
    all.filter((h) => h.name.toLowerCase() === name).map((h) => h.value);

  for (const [name, value] of Object.entries(EXPECTED)) {
    const found: string[] = values(name);
    expect(found, `${name} en ${response.url()}`).not.toHaveLength(0);
    // /api/ gets the header from both FastAPI and Nginx; repeated is fine,
    // a different value is not.
    for (const v of found) expect(v, `${name} en ${response.url()}`).toBe(value);
  }

  const csp: string[] = values('content-security-policy');
  expect(csp, `content-security-policy en ${response.url()}`).toHaveLength(1);
  for (const directive of CSP_DIRECTIVES) {
    expect(csp[0], `CSP en ${response.url()}`).toContain(directive);
  }
}

test.describe('flujo 4 · headers de seguridad', () => {
  test('/ (index.html)', async ({ request }) => {
    const response = await request.get('/');
    expect(response.status()).toBe(200);
    expectSecurityHeaders(response);
  });

  test('ruta del SPA que cae en index.html', async ({ request }) => {
    const response = await request.get('/alguna/ruta/del/cliente');
    expect(response.status()).toBe(200);
    expectSecurityHeaders(response);
  });

  test('/assets/… (JS y CSS con hash)', async ({ request }) => {
    const html: string = await (await request.get('/')).text();
    const assets: string[] = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1]);
    expect(assets.length, 'index.html enlaza assets').toBeGreaterThan(0);

    for (const asset of assets) {
      const response = await request.get(asset);
      expect(response.status(), asset).toBe(200);
      expectSecurityHeaders(response);
      // OPT-06: hashed assets are cached for a year.
      expect(response.headers()['cache-control'], asset).toContain('immutable');
    }
  });

  test('/api/health', async ({ request }) => {
    const response = await request.get('/api/health');
    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({ status: 'ok' });
    expectSecurityHeaders(response);
  });
});

/**
 * SEG-H13: HSTS is only sent when a TLS proxy in front says the request was
 * HTTPS (X-Forwarded-Proto: https). Over plain HTTP it must not appear.
 */
test.describe('flujo 4 · HSTS detrás de un proxy TLS (SEG-H13)', () => {
  async function paths(request: import('@playwright/test').APIRequestContext): Promise<string[]> {
    const html: string = await (await request.get('/')).text();
    const asset: string | undefined = html.match(/src="(\/assets\/[^"]+)"/)?.[1];
    expect(asset, 'index.html enlaza un asset').toBeTruthy();
    return ['/', '/alguna/ruta/del/cliente', asset as string, '/api/health'];
  }

  test('sin proxy TLS (HTTP directo) no se envía HSTS', async ({ request }) => {
    for (const path of await paths(request)) {
      const response = await request.get(path);
      expect(response.headers()['strict-transport-security'], path).toBeUndefined();
    }
  });

  test('con X-Forwarded-Proto: https se envía HSTS en /, /assets y /api', async ({ request }) => {
    for (const path of await paths(request)) {
      const response = await request.get(path, { headers: { 'X-Forwarded-Proto': 'https' } });
      const hsts: string[] = response
        .headersArray()
        .filter((h) => h.name.toLowerCase() === 'strict-transport-security')
        .map((h) => h.value);
      expect(hsts, path).toEqual(['max-age=31536000']);
    }
  });
});
