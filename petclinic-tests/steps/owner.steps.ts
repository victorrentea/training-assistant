import { expect } from '@playwright/test';
import { Given, When, Then } from './fixtures';

// ── Owner Search steps ────────────────────────────────────────────────────────

Given('I am on the owners search page', async ({ ownersSearchPage }) => {
  await ownersSearchPage.navigate();
});

When('I search for last name {string}', async ({ ownersSearchPage }, lastName: string) => {
  await ownersSearchPage.searchByLastName(lastName);
});

Then('I see {string} in the results', async ({ ownersSearchPage }, ownerName: string) => {
  const names = await ownersSearchPage.getOwnerNames();
  expect(names).toContain(ownerName);
});

Then('the result for {string} shows city {string}', async ({ ownersSearchPage }, ownerName: string, city: string) => {
  const actual = await ownersSearchPage.getCityForOwner(ownerName);
  expect(actual).toBe(city);
});

Then('I see no owners in the results', async ({ ownersSearchPage }) => {
  const names = await ownersSearchPage.getOwnerNames();
  expect(names).toHaveLength(0);
});

// ── Owner Form / CRUD steps ───────────────────────────────────────────────────

Given('I am on the add owner page', async ({ ownerFormPage }) => {
  await ownerFormPage.navigateToNew();
});

When(
  'I create owner {string} {string} at {string}, {string}, phone {string}',
  async ({ ownerFormPage, ownersSearchPage, ownerCleanup }, firstName: string, lastName: string, address: string, city: string, phone: string) => {
    await ownerFormPage.fillForm({ firstName, lastName, address, city, telephone: phone });
    await ownerFormPage.submitAdd();
    // After redirect to /owners the search form is blank — run a search so the results table populates
    await ownersSearchPage.searchByLastName(lastName);
    // Register for cleanup so teardown removes the created owner via REST API
    ownerCleanup.track(lastName);
  },
);

Then('I am on the owner detail page showing name {string}', async ({ ownerDetailPage }, fullName: string) => {
  const actual = await ownerDetailPage.getOwnerName();
  expect(actual).toBe(fullName);
});

Then('the owner detail shows city {string}', async ({ ownerDetailPage }, city: string) => {
  const actual = await ownerDetailPage.getOwnerField('City');
  expect(actual).toBe(city);
});

// ── Owner Detail navigation ───────────────────────────────────────────────────

Given('I am on the owner detail page for {string}', async ({ ownerDetailPage }, ownerName: string) => {
  await ownerDetailPage.navigateViaSearch(ownerName);
});
