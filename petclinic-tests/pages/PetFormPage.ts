import { Page } from '@playwright/test';
import { NavigationPage } from './NavigationPage';

/**
 * /petclinic/owners/:ownerId/pets/add  and  /petclinic/pets/:petId/edit
 * Fields: Name (required), Birth Date (datepicker, required), Type (combobox, required)
 * Owner field is readonly.
 * Buttons: < Back | Save Pet (new) / Update Pet (edit)
 * Note: "Save Pet" is disabled until Name, Birth Date, and Type are all filled.
 * Date format accepted: YYYY/MM/DD (Angular Material datepicker normalizes input)
 */
export class PetFormPage extends NavigationPage {
  constructor(page: Page) { super(page); }

  async fillName(name: string): Promise<void> {
    // Pet name input has id="name"
    await this.page.locator('#name').fill(name);
  }

  async fillBirthDate(date: string): Promise<void> {
    // Angular Material datepicker — input has name="birthDate" and aria-haspopup="dialog"
    const formatted = date.replace(/-/g, '/'); // Angular expects YYYY/MM/DD
    await this.page.locator('input[name="birthDate"]').fill(formatted);
    await this.page.keyboard.press('Tab');
  }

  async selectType(petType: string): Promise<void> {
    // Angular object-bound select: options have values like "2: Object" — select by label text instead
    await this.page.locator('select#type').selectOption({ label: petType });
  }

  async submitSave(): Promise<void> {
    await this.page.getByRole('button', { name: 'Save Pet' }).click();
    await this.page.waitForSelector('h2:has-text("Owner Information")');
  }

  async submitUpdate(): Promise<void> {
    await this.page.getByRole('button', { name: 'Update Pet' }).click();
    await this.page.waitForSelector('h2:has-text("Owner Information")');
  }

  async clickBack(): Promise<void> {
    await this.page.getByRole('button', { name: /back/i }).click();
  }
}

