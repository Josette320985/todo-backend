import { compose } from './support/compose';

/**
 * Builds and starts the real stack (Nginx + backend) with the E2E override and
 * waits for both healthchecks. Set E2E_REUSE_STACK=1 to skip it when the stack
 * is already up (`npm run stack:up`), which makes local reruns fast.
 */
export default function globalSetup(): void {
  if (process.env.E2E_REUSE_STACK === '1') return;
  // Start from an empty database and empty rate-limit counters.
  compose(['down', '-v', '--remove-orphans']);
  try {
    compose(['up', '-d', '--build', '--wait'], { timeoutMs: 600_000 });
  } catch (err) {
    console.error(compose(['logs', '--no-color', '--tail', '100']));
    throw err;
  }
}
