import { Page } from '@playwright/test';
import { NavigationPage } from './NavigationPage';

/**
 * /petclinic/vets — veterinarian list
 * Table columns: Name | Specialties
 * Row actions: Edit Vet | Delete Vet
 * Page actions: Home | Add Vet
 *
 * /petclinic/vets/add  and  /petclinic/vets/:id/edit
 * Fields: First Name (required), Last Name (required), Specialties selector
 * Buttons: < Back | Save Vet
 */
export class VetsPage extends NavigationPage {
  constructor(page: Page) { super(page); }

  async navigate(): Promise<void> {
    await this.goto('/vets');
    // Angular makes an async HTTP call for vet data; wait for at least one row to appear
    await this.page.waitForSelector('table.table tbody tr');
  }

  // Vet table: table.table-striped has thead + tbody with one <tr> per vet.
  private vetRows() {
    return this.page.locator('table.table tbody tr');
  }

  async getVetCount(): Promise<number> {
    return await this.vetRows().count();
  }

  /** Returns the specialties text for a given vet name (trimmed). */
  async getSpecialtiesForVet(vetName: string): Promise<string> {
    const row = this.vetRows().filter({ hasText: vetName });
    return (await row.locator('td').nth(1).innerText()).trim();
  }

  async vetExists(vetName: string): Promise<boolean> {
    return (await this.vetRows().filter({ hasText: vetName }).count()) > 0;
  }

  async clickAddVet(): Promise<void> {
    await this.page.getByRole('button', { name: 'Add Vet' }).click();
  }

  async clickDeleteVet(vetName: string): Promise<void> {
    const row = this.vetRows().filter({ hasText: vetName });
    await row.getByRole('button', { name: 'Delete Vet' }).click();
    // Deletion reloads the same /vets route; wait for the deleted row to disappear
    await this.page.locator('table.table tbody tr').filter({ hasText: vetName }).waitFor({ state: 'detached' });
  }

  /** Fills the new/edit vet form. Inputs are identified by id: #firstName, #lastName. */
  async fillVetForm(firstName: string, lastName: string): Promise<void> {
    await this.page.locator('#firstName').fill(firstName);
    await this.page.locator('#lastName').fill(lastName);
  }

  async submitSaveVet(): Promise<void> {
    await this.page.getByRole('button', { name: 'Save Vet' }).click();
    // Save Vet redirects back to /vets; wait for vet list to reload from server
    await this.page.waitForURL(/\/vets$/);
    await this.page.waitForSelector('table.table tbody tr');
  }
}

