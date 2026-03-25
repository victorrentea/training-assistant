import { Page } from '@playwright/test';

/** Base navigation helpers shared by all page objects. */
export class NavigationPage {
  constructor(public readonly page: Page) {}

  protected async goto(path: string): Promise<void> {
    await this.page.goto(`/petclinic${path}`);
  }

  async openOwnersSearch(): Promise<void> {
    await this.page.getByRole('button', { name: /owners/i }).click();
    await this.page.getByRole('link', { name: /search/i }).click();
  }

  async openAddOwner(): Promise<void> {
    await this.page.getByRole('button', { name: /owners/i }).click();
    await this.page.getByRole('link', { name: /add new/i }).first().click();
  }

  async openVetsList(): Promise<void> {
    await this.page.getByRole('button', { name: /veterinarians/i }).click();
    await this.page.getByRole('link', { name: /all/i }).click();
  }

  async openAddVet(): Promise<void> {
    await this.page.getByRole('button', { name: /veterinarians/i }).click();
    await this.page.getByRole('link', { name: /add new/i }).last().click();
  }
}

