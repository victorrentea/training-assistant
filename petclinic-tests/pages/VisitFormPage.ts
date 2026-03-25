import { Page } from '@playwright/test';
import { NavigationPage } from './NavigationPage';

/**
 * /petclinic/pets/:petId/visits/add
 * Shows: pet summary (Name, Birth Date, Type, Owner) — read-only
 * Fields: Date (datepicker, required), Description (required)
 * Section: "Previous Visits" table (Visit Date | Description | Actions)
 * Buttons: Back | Add Visit (disabled until Date + Description filled)
 */
export class VisitFormPage extends NavigationPage {
  constructor(page: Page) { super(page); }

  /**
   * Pet info table structure:
   *   <table class="table table-striped">
   *     <thead><tr>Name | Birth Date | Type | Owner</tr></thead>
   *     <tr>Leo | 2010-09-07 | cat | George Franklin</tr>  ← direct child, NOT in tbody
   *   </table>
   * Use 'table.table-striped > tr' to select direct-child data rows only.
   */
  async getDisplayedPetName(): Promise<string> {
    return (await this.page.locator('table.table-striped > tr').first().locator('td').nth(0).innerText()).trim();
  }

  async getDisplayedOwnerName(): Promise<string> {
    // Angular populates the owner cell asynchronously; wait until it has text
    const cell = this.page.locator('table.table-striped > tr').first().locator('td').nth(3);
    await this.page.waitForFunction(
      (sel: string) => {
        const el = document.querySelector(sel) as HTMLElement | null;
        return el ? el.innerText.trim().length > 0 : false;
      },
      'table.table-striped > tr:first-child td:nth-child(4)',
    );
    return (await cell.innerText()).trim();
  }

  async fillDate(date: string): Promise<void> {
    // Date input: name="date", aria-haspopup="dialog"
    const formatted = date.replace(/-/g, '/');
    await this.page.locator('input[name="date"]').fill(formatted);
    await this.page.keyboard.press('Tab');
  }

  async fillDescription(description: string): Promise<void> {
    // Description input has id="description"
    await this.page.locator('#description').fill(description);
  }

  async submitAddVisit(): Promise<void> {
    await this.page.getByRole('button', { name: 'Add Visit' }).click();
    await this.page.waitForSelector('h2:has-text("Owner Information")');
  }

  async clickBack(): Promise<void> {
    await this.page.getByRole('button', { name: 'Back' }).click();
  }
}

