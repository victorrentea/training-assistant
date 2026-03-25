import { Page } from '@playwright/test';
import { NavigationPage } from './NavigationPage';

/**
 * /petclinic/owners — owner search & results table.
 * Input id: #lastName  |  Results: <table class="table table-striped"> tbody tr
 * Cells per row: [0] Name (link), [1] Address, [2] City, [3] Telephone, [4] Pets
 */
export class OwnersSearchPage extends NavigationPage {
  constructor(page: Page) { super(page); }

  async navigate(): Promise<void> {
    await this.goto('/owners');
  }

  async searchByLastName(lastName: string): Promise<void> {
    await this.page.locator('#lastName').fill(lastName);
    await this.page.getByRole('button', { name: 'Find Owner' }).click();
  }

  async getOwnerNames(): Promise<string[]> {
    await this.page.waitForSelector('table.table tbody tr', { timeout: 3000 }).catch(() => {});
    const links = this.page.locator('table.table tbody tr td:first-child a');
    return await links.allInnerTexts();
  }

  async getCityForOwner(ownerName: string): Promise<string> {
    const row = this.page.locator('table.table tbody tr').filter({
      has: this.page.locator('td a', { hasText: ownerName }),
    });
    return (await row.locator('td').nth(2).innerText()).trim();
  }

  async clickOwner(ownerName: string): Promise<void> {
    await this.page.locator('table.table tbody tr td a', { hasText: ownerName }).click();
  }
}

