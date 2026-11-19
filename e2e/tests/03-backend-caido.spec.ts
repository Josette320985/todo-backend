import { expect, test } from '@playwright/test';
import { compose, startBackend, stopBackend } from '../support/compose';
import { createTask, registerViaUi, uniqueEmail } from '../support/app';

/**
 * Flow 3 (TEST-09, ERR-06 criterion): if the backend is down, creating a task
 * shows a connection message, never "Revisa los datos" (which blames the user
 * for a server problem).
 */
test.describe('flujo 3 · backend detenido', () => {
  test('crear una tarea con el backend detenido → mensaje de conexión', async ({ page }) => {
    await registerViaUi(page, uniqueEmail('flujo3'));

    // Behind Nginx a stopped backend is not "no response": Nginx keeps trying
    // the old container IP and only answers 502 after 40 s to 2 min (measured;
    // "Host is unreachable" once ARP gives up). The user must get feedback well
    // before that: ERR-07's 10 s client timeout does it, so 30 s is the bound.
    test.setTimeout(120_000);
    stopBackend();
    try {
      await createTask(page, 'Tarea sin servidor');

      const alert = page.getByRole('alert');
      await expect(alert).toBeVisible({ timeout: 30_000 });
      await expect(alert).not.toContainText('Revisa los datos');
      // ERR-06: connection message ("No hay conexión con el servidor…"), the
      // 5xx one if 502 is mapped as a server error, or ERR-07's timeout one.
      await expect(alert).toContainText(/conexión|servidor/i);
    } finally {
      // The tmpfs database is gone after the stop; later flows create their own users.
      startBackend();
      // Nginx resolves "backend" once, at startup. A restarted backend container
      // may get another IP, so Nginx is restarted too or later flows get 502.
      compose(['restart', 'frontend']);
      compose(['up', '-d', '--wait', 'frontend']);
    }
  });

  test('crear una tarea sin red → mensaje de conexión', async ({ page, context }) => {
    await registerViaUi(page, uniqueEmail('flujo3-offline'));

    // The request never gets a response at all: ERR-06's "sin respuesta" branch.
    await context.setOffline(true);
    await createTask(page, 'Tarea sin red');

    const alert = page.getByRole('alert');
    await expect(alert).toBeVisible();
    await expect(alert).not.toContainText('Revisa los datos');
    await expect(alert).toContainText(/conexión/i);
    await context.setOffline(false);
  });
});
