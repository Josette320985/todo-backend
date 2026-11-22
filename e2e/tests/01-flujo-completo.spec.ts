import { expect, test } from '@playwright/test';
import {
  createTask,
  deleteButton,
  editButton,
  loginHeading,
  registerViaUi,
  taskRow,
  uniqueEmail,
} from '../support/app';

/**
 * Flow 1 (TEST-09): registro → crear → marcar → editar → eliminar → deshacer → cerrar sesión.
 *
 * Every step is checked against the server too (reload), not only the DOM, so
 * an optimistic update that never reached the backend does not pass.
 */
test('flujo 1 · registro, CRUD con deshacer y cierre de sesión', async ({ page, request }) => {
  const email: string = uniqueEmail('flujo1');
  const title: string = 'Comprar leche';
  const edited: string = 'Comprar leche deslactosada';

  await test.step('registro (entra directo a la lista)', async () => {
    await registerViaUi(page, email);
    await expect(page.getByText('No hay tareas pendientes.')).toBeVisible();
  });

  await test.step('crear', async () => {
    await createTask(page, title);
    await expect(taskRow(page, title)).toBeVisible();
    await expect(page.getByPlaceholder('Nueva tarea...')).toHaveValue('');
  });

  await test.step('marcar como completada', async () => {
    // click(), not check(): the checkbox is controlled and only changes after
    // the PUT, so check() would fail on its immediate state assertion.
    await taskRow(page, title).getByRole('checkbox').click();
    await expect(taskRow(page, title).getByRole('checkbox')).toBeChecked();
    await page.reload();
    await expect(taskRow(page, title).getByRole('checkbox')).toBeChecked();
  });

  await test.step('editar el título', async () => {
    await editButton(taskRow(page, title)).click();
    const editing = page
      .locator('.list-group-item')
      .filter({ has: page.getByRole('button', { name: 'Guardar' }) });
    await editing.getByRole('textbox').first().fill(edited);
    await editing.getByRole('button', { name: 'Guardar' }).click();
    await expect(taskRow(page, edited)).toBeVisible();
    await page.reload();
    await expect(taskRow(page, edited)).toBeVisible();
    // Editing the title does not reset the completed state.
    await expect(taskRow(page, edited).getByRole('checkbox')).toBeChecked();
  });

  await test.step('eliminar', async () => {
    await deleteButton(taskRow(page, edited)).click();
    await expect(taskRow(page, edited)).toHaveCount(0);
  });

  await test.step('deshacer (UX-04: toast "Tarea eliminada · Deshacer")', async () => {
    await expect(page.getByText(/tarea eliminada/i)).toBeVisible();
    await page.getByRole('button', { name: /deshacer/i }).click();
    // UX-04 criterion: the task is left exactly as it was before deleting.
    await expect(taskRow(page, edited)).toBeVisible();
    await expect(taskRow(page, edited).getByRole('checkbox')).toBeChecked();
    await page.reload();
    await expect(taskRow(page, edited)).toBeVisible();
    await expect(taskRow(page, edited).getByRole('checkbox')).toBeChecked();
  });

  await test.step('cerrar sesión (y el token queda revocado en el servidor, SEG-H10)', async () => {
    const token: string | null = await page.evaluate(() => localStorage.getItem('token'));
    expect(token).toBeTruthy();

    await page.getByRole('button', { name: /cerrar sesión/i }).click();
    await expect(loginHeading(page)).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem('token'))).toBeNull();

    await page.reload();
    await expect(loginHeading(page)).toBeVisible();

    const reused = await request.get('/api/v1/tasks/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(reused.status()).toBe(401);
  });
});
