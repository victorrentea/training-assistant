import { expect } from '@playwright/test';
import { Given, When, Then } from './fixtures';

Given('I am on the veterinarians list page', async ({ vetsPage }) => {
  await vetsPage.navigate();
});

Then('the list contains {int} veterinarians', async ({ vetsPage }, count: number) => {
  expect(await vetsPage.getVetCount()).toBe(count);
});

Then('vet {string} has specialty {string}', async ({ vetsPage }, vetName: string, specialty: string) => {
  const specialties = await vetsPage.getSpecialtiesForVet(vetName);
  expect(specialties).toContain(specialty);
});

Then(
  'vet {string} has specialties {string} and {string}',
  async ({ vetsPage }, vetName: string, s1: string, s2: string) => {
    const specialties = await vetsPage.getSpecialtiesForVet(vetName);
    expect(specialties).toContain(s1);
    expect(specialties).toContain(s2);
  },
);

Then('vet {string} has no specialties listed', async ({ vetsPage }, vetName: string) => {
  const specialties = await vetsPage.getSpecialtiesForVet(vetName);
  expect(specialties.trim()).toBe('');
});

Given('I navigate to add a new veterinarian', async ({ vetsPage }) => {
  await vetsPage.navigate();
  await vetsPage.clickAddVet();
});

When(
  'I create vet {string} {string}',
  async ({ vetsPage }, firstName: string, lastName: string) => {
    await vetsPage.fillVetForm(firstName, lastName);
    await vetsPage.submitSaveVet();
  },
);

Then('{string} appears in the veterinarians list', async ({ vetsPage }, vetName: string) => {
  expect(await vetsPage.vetExists(vetName)).toBe(true);
});

When('I delete vet {string}', async ({ vetsPage }, vetName: string) => {
  await vetsPage.clickDeleteVet(vetName);
});

Then('{string} no longer appears in the veterinarians list', async ({ vetsPage }, vetName: string) => {
  expect(await vetsPage.vetExists(vetName)).toBe(false);
});

