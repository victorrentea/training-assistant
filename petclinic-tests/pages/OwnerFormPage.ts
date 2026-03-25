import { Page } from '@playwright/test';
import { NavigationPage } from './NavigationPage';

/**
 * /petclinic/owners/add  and  /petclinic/owners/:id/edit
 * Fields: First Name, Last Name, Address, City, Telephone (all required)
 * Buttons: Back | Add Owner (new) / Update Owner (edit)
 */
export class OwnerFormPage extends NavigationPage {
  constructor(page: Page) { super(page); }

  async navigateToNew(): Promise<void> {
    await this.goto('/owners/add');
  }

  async fillForm(data: {
    firstName: string;
    lastName: string;
    address: string;
    city: string;
    telephone: string;
  }): Promise<void> {
    // Inputs identified by id: #firstName, #lastName, #address, #city, #telephone
    await this.page.locator('#firstName').fill(data.firstName);
    await this.page.locator('#lastName').fill(data.lastName);
    await this.page.locator('#address').fill(data.address);
    await this.page.locator('#city').fill(data.city);
    await this.page.locator('#telephone').fill(data.telephone);
  }

  async submitAdd(): Promise<void> {
    await this.page.getByRole('button', { name: 'Add Owner' }).click();
    // App redirects to the owners list page after creation
    await this.page.waitForURL(/\/owners$/);
  }

  async submitUpdate(): Promise<void> {
    await this.page.getByRole('button', { name: 'Update Owner' }).click();
    await this.page.waitForURL(/\/owners\/\d+$/);
  }

  async clickBack(): Promise<void> {
    await this.page.getByRole('button', { name: 'Back' }).click();
  }
}

