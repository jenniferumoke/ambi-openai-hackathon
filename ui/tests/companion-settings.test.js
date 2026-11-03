import test from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_SETTINGS, normalizeSettings, colorFilter } from '../src/companion-settings.js';

test('saved appearance is bounded and unsupported settings cannot become CSS', () => {
  assert.deepEqual(normalizeSettings(null), DEFAULT_SETTINGS);
  assert.deepEqual(normalizeSettings({ color: 'url(evil)', background: 'red', scale: NaN, animated: 'false', displayName: '  ' }), DEFAULT_SETTINGS);
  const settings = normalizeSettings({ displayName: '  My Ambi  ', color: 'rose', background: 'black', scale: 200, animated: false });
  assert.deepEqual(settings, { displayName: 'My Ambi', color: 'rose', background: 'black', scale: .95, animated: false });
  assert.equal(normalizeSettings({ displayName: 'x'.repeat(40), scale: -1 }).displayName.length, 24);
  assert.equal(normalizeSettings({ scale: -1 }).scale, .35);
  assert.equal(colorFilter('url(evil)'), 'none');
});

test('preferences survive a JSON save/load without losing the still setting', () => {
  const original = normalizeSettings({ displayName: 'Milo', color: 'lilac', background: 'black', scale: .65, animated: false });
  assert.deepEqual(normalizeSettings(JSON.parse(JSON.stringify(original))), original);
});


test('navy and blue are the default and survive a save/load', () => {
  assert.equal(DEFAULT_SETTINGS.color, 'blue');
  assert.equal(DEFAULT_SETTINGS.background, 'navy');
  assert.deepEqual(normalizeSettings(JSON.parse(JSON.stringify(DEFAULT_SETTINGS))), DEFAULT_SETTINGS);
});
