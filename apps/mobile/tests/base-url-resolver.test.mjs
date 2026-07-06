import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveBaseUrl } from '../src/domain/baseUrlResolver.mjs';

function makeProbe(results) {
  const calls = [];
  return {
    calls,
    fn: async (url, method, timeoutMs) => {
      calls.push({ url, method, timeoutMs });
      const result = results[url];
      if (!result) {
        throw new Error(`probe: no handler for ${url}`);
      }
      if (result === 'fail') {
        throw new Error(`probe: ${url} unreachable`);
      }
      return result;
    },
  };
}

test('resolveBaseUrl returns primary when the probe succeeds', async () => {
  const probe = makeProbe({ 'http://local': { ok: true } });
  const resolved = await resolveBaseUrl({
    primary: 'http://local',
    fallback: 'https://remote',
    probe: probe.fn,
  });
  assert.equal(resolved, 'http://local');
  assert.equal(probe.calls.length, 1);
  assert.equal(probe.calls[0].url, 'http://local');
});

test('resolveBaseUrl falls back to remote when primary probe fails', async () => {
  const probe = makeProbe({ 'http://local': 'fail', 'https://remote': { ok: true } });
  const resolved = await resolveBaseUrl({
    primary: 'http://local',
    fallback: 'https://remote',
    probe: probe.fn,
  });
  assert.equal(resolved, 'https://remote');
  assert.equal(probe.calls.length, 2);
  assert.equal(probe.calls[0].url, 'http://local');
  assert.equal(probe.calls[1].url, 'https://remote');
});

test('resolveBaseUrl returns primary when both probes fail and no better option', async () => {
  const probe = makeProbe({ 'http://local': 'fail', 'https://remote': 'fail' });
  const resolved = await resolveBaseUrl({
    primary: 'http://local',
    fallback: 'https://remote',
    probe: probe.fn,
  });
  assert.equal(resolved, 'http://local');
});

test('resolveBaseUrl returns primary when fallback is null', async () => {
  const probe = makeProbe({ 'http://local': 'fail' });
  const resolved = await resolveBaseUrl({
    primary: 'http://local',
    fallback: null,
    probe: probe.fn,
  });
  assert.equal(resolved, 'http://local');
  assert.equal(probe.calls.length, 1);
});

test('resolveBaseUrl does not probe fallback when fallback is null', async () => {
  const probe = makeProbe({ 'http://local': { ok: true } });
  const resolved = await resolveBaseUrl({
    primary: 'http://local',
    fallback: null,
    probe: probe.fn,
  });
  assert.equal(resolved, 'http://local');
  assert.equal(probe.calls.length, 1);
});
