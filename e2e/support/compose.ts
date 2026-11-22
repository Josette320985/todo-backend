import { execFileSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/** todo-backend/, where the real docker-compose.yml lives. */
const BACKEND_DIR: string = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');

/** Separate project, so the run never touches the developer's stack. */
export const PROJECT: string = process.env.E2E_PROJECT ?? 'todo-e2e';

export const PORT: string = process.env.E2E_PORT ?? '3100';

export const BASE_URL: string = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${PORT}`;

const FILES: string[] = ['-f', 'docker-compose.yml', '-f', 'e2e/docker-compose.e2e.yml'];

/**
 * Runs `docker compose -p todo-e2e -f docker-compose.yml -f e2e/docker-compose.e2e.yml <args>`
 * from todo-backend/ and returns stdout.
 */
export function compose(args: string[], options: { timeoutMs?: number } = {}): string {
  return execFileSync('docker', ['compose', '-p', PROJECT, ...FILES, ...args], {
    cwd: BACKEND_DIR,
    env: { ...process.env, E2E_PORT: PORT },
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: options.timeoutMs ?? 120_000,
  });
}

/** Stops the backend container. Its tmpfs database is lost, which is fine: every flow creates its own user. */
export function stopBackend(): void {
  compose(['stop', 'backend']);
}

/** Starts the backend again and waits until its healthcheck passes. */
export function startBackend(): void {
  compose(['up', '-d', '--wait', 'backend'], { timeoutMs: 120_000 });
}

/** Result printed by e2e/clients/http_client.py. */
export interface ClientResult {
  statuses: number[];
}

/**
 * Runs the stdlib HTTP client inside client-a or client-b. Each container has
 * its own IP on the compose network, so the backend sees two different clients.
 */
export function fromClient(
  client: 'client-a' | 'client-b',
  args: string[],
): ClientResult {
  const out: string = compose(['exec', '-T', client, 'python', '/e2e-clients/http_client.py', ...args]);
  return JSON.parse(out.trim().split('\n').at(-1) ?? '{}') as ClientResult;
}

/** IP of a service on the compose network (for test diagnostics). */
export function serviceIp(service: string): string {
  const id: string = compose(['ps', '-q', service]).trim();
  return execFileSync(
    'docker',
    ['inspect', '-f', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', id],
    { encoding: 'utf8' },
  ).trim();
}
