import { compose } from './support/compose';

/**
 * Removes the stack and its disposable database. Set E2E_KEEP_STACK=1 to leave
 * it running for debugging (`docker compose -p todo-e2e logs`).
 */
export default function globalTeardown(): void {
  if (process.env.E2E_KEEP_STACK === '1' || process.env.E2E_REUSE_STACK === '1') return;
  compose(['down', '-v', '--remove-orphans']);
}
