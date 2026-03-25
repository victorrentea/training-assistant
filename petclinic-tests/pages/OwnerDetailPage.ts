import { Page } from '@playwright/test';
import { NavigationPage } from './NavigationPage';

/**
 * /petclinic/owners/:id — owner detail page.
 * Owner info: <table> rows with <th> label and <td> value.
 *   Name cell: <b class="ownerFullName">
 * Pets section: one <app-pet-list> per pet.
 *   Pet name: app-pet-list dd (first dd = name)
 *   Buttons: Edit Pet, Delete Pet, Add Visit — inside app-pet-list
 * Visits (per pet): inside <app-visit-list> adjacent to each app-pet-list
 */
export class OwnerDetailPage extends NavigationPage {
  constructor(page: Page) { super(page); }

  async navigate(ownerId: number): Promise<void> {
    await this.goto(`/owners/${ownerId}`);
  }

  async navigateViaSearch(ownerName: string): Promise<void> {
    const lastName = ownerName.split(' ').pop()!;
    await this.goto('/owners');
    await this.page.locator('#lastName').fill(lastName);
    await this.page.getByRole('button', { name: 'Find Owner' }).click();
    await this.page.locator('table.table tbody tr td a', { hasText: ownerName }).click();
    await this.page.waitForURL(/\/owners\/\d+$/);
  }

  async getOwnerName(): Promise<string> {
    return (await this.page.locator('b.ownerFullName').innerText()).trim();
  }

  async getOwnerField(label: string): Promise<string> {
    const row = this.page.locator('table tr').filter({ hasText: label });
    return (await row.locator('td').innerText()).trim();
  }

  /** Returns all pet names shown in the "Pets and Visits" section. */
  async getPetNames(): Promise<string[]> {
    // Each app-pet-list has a <dl>; first <dd> is the pet name.
    const nameDds = this.page.locator('app-pet-list dl dd').first().locator('xpath=ancestor::dl').locator('dd:first-of-type');
    // Simpler: get all first dd's across all app-pet-list components
    const pets = this.page.locator('app-pet-list').locator('dd').first();
    const all = this.page.locator('app-pet-list');
    const count = await all.count();
    const names: string[] = [];
    for (let i = 0; i < count; i++) {
      const name = await all.nth(i).locator('dd').first().innerText();
      names.push(name.trim());
    }
    return names;
  }

  /** Clicks "Add New Pet" button and waits for the add-pet form heading to appear. */
  async clickAddNewPet(): Promise<void> {
    await this.page.getByRole('button', { name: 'Add New Pet' }).click();
    // waitForURL with 'load' hangs because Angular fetches pet types async;
    // wait for the heading instead — it appears as soon as the component renders.
    await this.page.waitForSelector('h2:has-text("Add Pet")');
  }

  /** Clicks "Edit Pet" for the named pet and waits for edit form heading to appear (exact match). */
  async clickEditPetByName(petName: string): Promise<void> {
    const petList = this.page.locator('app-pet-list').filter({ hasText: petName });
    await petList.getByRole('button', { name: 'Edit Pet' }).click();
    // 'Pets and Visits' also contains the text "Pet" — wait for EXACT heading "Pet"
    await this.page.locator('h2').filter({ hasText: /^Pet$/ }).waitFor();
  }

  /** Clicks "Delete Pet" for the named pet and waits for the row to disappear. */
  async clickDeletePetByName(petName: string): Promise<void> {
    const petList = this.page.locator('app-pet-list').filter({ hasText: petName });
    await petList.getByRole('button', { name: 'Delete Pet' }).click();
    await this.page.locator('app-pet-list').filter({ hasText: petName }).waitFor({ state: 'detached' });
  }

  /** Clicks "Add Visit" for the named pet and waits for the visit form heading to appear. */
  async clickAddVisitForPet(petName: string): Promise<void> {
    const petList = this.page.locator('app-pet-list').filter({ hasText: petName });
    await petList.getByRole('button', { name: 'Add Visit' }).click();
    await this.page.waitForSelector('h2:has-text("New Visit")');
  }

  /** Returns all visit descriptions for the named pet. */
  async getVisitDescriptionsForPet(petName: string): Promise<string[]> {
    const petList = this.page.locator('app-pet-list').filter({ hasText: petName });
    // app-visit-list is inside the same app-pet-list; visits are in tbody tr td:nth-child(2)
    const descCells = petList.locator('app-visit-list tbody tr td').nth(1);
    const rows = petList.locator('app-visit-list tbody tr');
    const count = await rows.count();
    const descs: string[] = [];
    for (let i = 0; i < count; i++) {
      descs.push((await rows.nth(i).locator('td').nth(1).innerText()).trim());
    }
    return descs;
  }

  async clickEditOwner(): Promise<void> {
    await this.page.getByRole('button', { name: 'Edit Owner' }).click();
    await this.page.waitForURL(/\/owners\/\d+\/edit$/);
  }
}

