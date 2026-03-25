import { test as base, createBdd } from 'playwright-bdd';
import { type APIRequestContext } from '@playwright/test';
import { OwnersSearchPage } from '../pages/OwnersSearchPage';
import { OwnerDetailPage } from '../pages/OwnerDetailPage';
import { OwnerFormPage } from '../pages/OwnerFormPage';
import { PetFormPage } from '../pages/PetFormPage';
import { VisitFormPage } from '../pages/VisitFormPage';
import { VetsPage } from '../pages/VetsPage';

/**
 * Tracks owners created during a test run so they can be deleted via the
 * PetClinic REST API in teardown — preventing data accumulation across runs.
 */
export class OwnerCleanup {
  private readonly lastNames = new Set<string>();

  track(lastName: string): void {
    this.lastNames.add(lastName);
  }

  async deleteAll(request: APIRequestContext): Promise<void> {
    for (const lastName of this.lastNames) {
      const resp = await request.get(`/petclinic/api/owners?lastName=${encodeURIComponent(lastName)}`);
      if (!resp.ok()) continue;
      const owners: Array<{ id: number }> = await resp.json();
      for (const owner of owners) {
        await request.delete(`/petclinic/api/owners/${owner.id}`);
      }
    }
    this.lastNames.clear();
  }
}

/** All page objects wired as Playwright fixtures and shared across all step files. */
export const test = base.extend<{
  ownersSearchPage: OwnersSearchPage;
  ownerDetailPage: OwnerDetailPage;
  ownerFormPage: OwnerFormPage;
  petFormPage: PetFormPage;
  visitFormPage: VisitFormPage;
  vetsPage: VetsPage;
  ownerCleanup: OwnerCleanup;
}>({
  ownersSearchPage: async ({ page }, use) => use(new OwnersSearchPage(page)),
  ownerDetailPage:  async ({ page }, use) => use(new OwnerDetailPage(page)),
  ownerFormPage:    async ({ page }, use) => use(new OwnerFormPage(page)),
  petFormPage:      async ({ page }, use) => use(new PetFormPage(page)),
  visitFormPage:    async ({ page }, use) => use(new VisitFormPage(page)),
  vetsPage:         async ({ page }, use) => use(new VetsPage(page)),
  ownerCleanup: async ({ request }, use) => {
    const cleanup = new OwnerCleanup();
    await use(cleanup);
    // teardown: runs even when the test fails
    await cleanup.deleteAll(request);
  },
});

export const { Given, When, Then } = createBdd(test);

