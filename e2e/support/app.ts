import { randomBytes } from 'node:crypto';
import { expect, type Locator, type Page } from '@playwright/test';

/** Passes the backend rules: 8+ characters, at least one letter and one digit. */
export const PASSWORD: string = 'E2ePassw0rd';

/** A fresh email per call: every flow gets its own user in the throwaway database. */
export function uniqueEmail(flow: string): string {
  return `e2e-${flow}-${Date.now()}-${randomBytes(3).toString('hex')}@example.com`;
}

/** Registers through the real form ("Registrarse y Entrar" registers and logs in). */
export async function registerViaUi(page: Page, email: string, password: string = PASSWORD): Promise<void> {
  await page.goto('/');
  await page.getByRole('button', { name: /no tienes cuenta/i }).click();
  // By label, not by type: UX-05 made the email field type="text" (with
  // inputMode="email") so it follows the backend's email rules.
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Contraseña').fill(password);
  await page.getByRole('button', { name: /registrarse/i }).click();
  await expect(page.getByRole('heading', { name: 'Mis Tareas' })).toBeVisible();
}

/** Creates a task from the "Nueva tarea..." input. */
export async function createTask(page: Page, title: string): Promise<void> {
  await page.getByPlaceholder('Nueva tarea...').fill(title);
  await page.getByRole('button', { name: 'Agregar' }).click();
}

/**
 * Row of a task in read mode, matched by its exact title.
 * Bootstrap's ListGroup.Item renders `.list-group-item`. The title is matched as
 * text, not as the checkbox name: Form.Check without `id` does not link its label.
 */
export function taskRow(page: Page, title: string): Locator {
  return page
    .locator('.list-group-item')
    .filter({ has: page.getByText(title, { exact: true }) });
}

/** Edit button of a row: today "Modificar", an icon button with aria-label after UX-07. */
export function editButton(row: Locator): Locator {
  return row.getByRole('button', { name: /modificar|editar/i });
}

/** Delete button of a row: today "Eliminar", an icon button with aria-label after UX-07. */
export function deleteButton(row: Locator): Locator {
  return row.getByRole('button', { name: /eliminar|borrar/i });
}

/** Heading of the login form, shown whenever there is no session. */
export function loginHeading(page: Page): Locator {
  return page.getByRole('heading', { name: /iniciar sesión/i });
}
