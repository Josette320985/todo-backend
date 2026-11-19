import { expect, test } from '@playwright/test';
import { PASSWORD, uniqueEmail } from '../support/app';
import { fromClient, serviceIp } from '../support/compose';

/**
 * Flow 5 (TEST-09, SEG-02 acceptance criteria): two clients with different IPs
 * behind Nginx have separate rate-limit counters, and a forged X-Forwarded-For
 * does not move a client to another counter.
 *
 * client-a and client-b are two containers on the compose network: each has
 * its own IP and both go through Nginx (http://frontend), like real users.
 *
 * Runs last: until SEG-02 is fixed, client A's failures block login for every
 * client (all requests share Nginx's IP) for 60 seconds.
 */
test('flujo 5 · dos clientes con IP distinta tienen contadores separados', async () => {
  const victim: string = uniqueEmail('flujo5-b');
  test.info().annotations.push({
    type: 'ips',
    description: `client-a=${serviceIp('client-a')} client-b=${serviceIp('client-b')} nginx=${serviceIp('frontend')}`,
  });

  await test.step('client B se registra', async () => {
    expect(fromClient('client-b', ['register', victim, PASSWORD]).statuses).toEqual([201]);
  });

  await test.step('client A acumula 10 fallos y queda bloqueado', async () => {
    const failures = fromClient('client-a', ['login', uniqueEmail('flujo5-a'), 'Wrong-pass-1', '--times', '10']);
    // Soft: with a shared counter (SEG-02 not fixed) earlier flows' logins
    // already count against A, so a 429 can show up here; the step that
    // decides is client B's login below.
    expect.soft(failures.statuses, 'los 10 fallos de A son 401').toEqual(Array(10).fill(401));
    // Without this the test would pass with the limiter turned off.
    expect(fromClient('client-a', ['login', victim, PASSWORD]).statuses).toEqual([429]);
  });

  await test.step('client B (otra IP) inicia sesión: 200, no 429', async () => {
    expect(fromClient('client-b', ['login', victim, PASSWORD]).statuses).toEqual([200]);
  });

  await test.step('client A con un X-Forwarded-For inventado sigue bloqueado', async () => {
    const forged = fromClient('client-a', ['login', victim, PASSWORD, '--xff', '203.0.113.7']);
    expect(forged.statuses).toEqual([429]);
  });
});
