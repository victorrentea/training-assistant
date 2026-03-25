import { expect } from '@playwright/test';
import { Given, When, Then } from './fixtures';

When(
  'I add a new pet with name {string}, birth date {string}, type {string}',
  async ({ ownerDetailPage, petFormPage }, petName: string, birthDate: string, petType: string) => {
    await ownerDetailPage.clickAddNewPet();
    await petFormPage.fillName(petName);
    await petFormPage.fillBirthDate(birthDate);
    await petFormPage.selectType(petType);
    await petFormPage.submitSave();
  },
);

Then('pet {string} appears in the pets section', async ({ ownerDetailPage }, petName: string) => {
  const names = await ownerDetailPage.getPetNames();
  expect(names).toContain(petName);
});

When('I rename pet {string} to {string}', async ({ ownerDetailPage, petFormPage }, oldName: string, newName: string) => {
  await ownerDetailPage.clickEditPetByName(oldName);
  await petFormPage.fillName(newName);
  await petFormPage.submitUpdate();
});

When('I delete pet {string}', async ({ ownerDetailPage }, petName: string) => {
  await ownerDetailPage.clickDeletePetByName(petName);
});

Then('pet {string} is no longer in the pets section', async ({ ownerDetailPage }, petName: string) => {
  const names = await ownerDetailPage.getPetNames();
  expect(names).not.toContain(petName);
});

