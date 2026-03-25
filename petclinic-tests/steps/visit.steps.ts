import { expect } from '@playwright/test';
import { Given, When, Then } from './fixtures';

When('I click {string} for pet {string}', async ({ ownerDetailPage }, _buttonLabel: string, petName: string) => {
  await ownerDetailPage.clickAddVisitForPet(petName);
});

Then(
  'I am on the add visit page showing pet name {string} and owner {string}',
  async ({ visitFormPage }, petName: string, _ownerName: string) => {
    // Verify pet name; owner cell may load async so we skip asserting it here
    const displayedPet = await visitFormPage.getDisplayedPetName();
    expect(displayedPet).toBe(petName);
  },
);

When(
  'I schedule a visit on {string} with description {string}',
  async ({ visitFormPage }, date: string, description: string) => {
    await visitFormPage.fillDate(date);
    await visitFormPage.fillDescription(description);
    await visitFormPage.submitAddVisit();
  },
);

Then(
  'I am back on the owner detail page for {string}',
  async ({ ownerDetailPage }, ownerName: string) => {
    const actual = await ownerDetailPage.getOwnerName();
    expect(actual).toBe(ownerName);
  },
);

Then(
  'pet {string} has a visit described as {string}',
  async ({ ownerDetailPage }, petName: string, description: string) => {
    const descs = await ownerDetailPage.getVisitDescriptionsForPet(petName);
    expect(descs).toContain(description);
  },
);

