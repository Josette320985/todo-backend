import { expect, test } from '@playwright/test';
import { PASSWORD, uniqueEmail } from '../support/app';
import { fromClient, serviceIp } from '../support/compose';

/**
 * Flow 5 (TEST-09, SEG-02 acceptance criteria): two clients with different IPs
 * behind Nginx have separate rate-limit counters, a forged X-Forwarded-For
 * does not move a client to another counter, and one account under attack is
 * locked without locking the others.
 *
 * SEG-02 has two limits: 10 failed logins per IP and 5 per IP + email. A
 * blocked attempt does not count towards the IP limit.
 *
 * client-a and client-b are two containers on the compose network: each has
 * its own IP and both go through Nginx (http://frontend), like real users.
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

  await test.step('client A falla 10 veces con cuentas distintas y su IP queda bloqueada', async () => {
    // One email per attempt, so only the per-IP limit (10) applies.
    const failures = fromClient('client-a', ['login', uniqueEmail('flujo5-a'), 'Wrong-pass-1', '--times', '10', '--vary-email']);
    expect(failures.statuses, 'los 10 fallos de A son 401').toEqual(Array(10).fill(401));
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

  await test.step('client B ataca una sola cuenta: se bloquea esa cuenta, no las demás', async () => {
    const target: string = uniqueEmail('flujo5-target');
    // 5 failures per IP + email, then 429 for that account from this IP.
    expect(fromClient('client-b', ['login', target, 'Wrong-pass-1', '--times', '6']).statuses)
      .toEqual([401, 401, 401, 401, 401, 429]);
    // B's IP has only 5 failures (the blocked one does not count): other accounts still log in.
    expect(fromClient('client-b', ['login', victim, PASSWORD]).statuses).toEqual([200]);
  });
});
