import { createHmac } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { loginHeading } from '../support/app';

/** A well-formed HS256 JWT signed with a key the backend does not know. */
function foreignJwt(): string {
  const b64 = (value: object): string => Buffer.from(JSON.stringify(value)).toString('base64url');
  const header: string = b64({ alg: 'HS256', typ: 'JWT' });
  const payload: string = b64({ sub: '1', ver: 0, exp: Math.floor(Date.now() / 1000) + 3600 });
  const signature: string = createHmac('sha256', 'not-the-server-key')
    .update(`${header}.${payload}`)
    .digest('base64url');
  return `${header}.${payload}.${signature}`;
}

/**
 * Flow 2 (TEST-09, UX-06 criterion): with an invalid token in localStorage the
 * user sees why they are back at the login, not just a jump to the form.
 */
for (const [name, token] of [
  ['firmado con otra clave', foreignJwt()],
  ['basura', 'esto-no-es-un-jwt'],
] as const) {
  test(`flujo 2 · token inválido (${name}) → aviso de sesión expirada`, async ({ page }) => {
    await page.addInitScript((value: string) => {
      // Only on the first load: the app must be able to clear it afterwards.
      if (!sessionStorage.getItem('e2e-token-planted')) {
        sessionStorage.setItem('e2e-token-planted', '1');
        localStorage.setItem('token', value);
      }
    }, token);

    const tasksCall = page.waitForResponse((r) => r.url().includes('/api/v1/tasks'));
    await page.goto('/');
    expect((await tasksCall).status()).toBe(401);

    await expect(loginHeading(page)).toBeVisible();
    await expect(page.getByText('Tu sesión expiró. Vuelve a iniciar sesión.')).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem('token'))).toBeNull();
  });
}
