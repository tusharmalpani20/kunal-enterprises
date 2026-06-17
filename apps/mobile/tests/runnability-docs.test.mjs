import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';

const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const readme = readFileSync(new URL('../README.md', import.meta.url), 'utf8');
const envExample = readFileSync(new URL('../.env.example', import.meta.url), 'utf8');
const configSource = readFileSync(new URL('../src/constants/config.ts', import.meta.url), 'utf8');
const deliveryAudit = readFileSync(new URL('../../../docs/11-delivery-audit.md', import.meta.url), 'utf8');
const gitignore = readFileSync(new URL('../../../.gitignore', import.meta.url), 'utf8');
const mobileRoot = new URL('..', import.meta.url);

test('mobile package exposes run, test, and typecheck commands for Expo handoff', () => {
	assert.equal(packageJson.scripts.start, 'expo start');
	assert.equal(packageJson.scripts.test, 'node --test tests/*.test.mjs');
	assert.equal(packageJson.scripts.typecheck, 'tsc --noEmit');
});

test('mobile package pins Expo SDK compatible runtime versions', () => {
	assert.equal(packageJson.dependencies.expo, '~54.0.0');
	assert.equal(packageJson.dependencies['@react-native-async-storage/async-storage'], '2.2.0');
	assert.equal(packageJson.dependencies['expo-constants'], '~18.0.13');
	assert.equal(packageJson.dependencies['expo-linking'], '~8.0.12');
	assert.equal(packageJson.dependencies['expo-router'], '~6.0.23');
	assert.equal(packageJson.dependencies.react, '19.1.0');
	assert.equal(packageJson.dependencies['react-native'], '0.81.5');
	assert.equal(packageJson.dependencies['react-native-svg'], '15.12.1');
	assert.equal(packageJson.devDependencies['@types/react'], '~19.1.10');
	assert.equal(packageJson.devDependencies.typescript, '~5.9.2');
	assert.equal(packageJson.overrides.postcss, '8.5.10');
});

test('mobile README documents install, launch, test, and typecheck verification', () => {
	for (const command of ['bun install', 'bun run start', 'bun test', 'bun run typecheck']) {
		assert.match(readme, new RegExp(command.replaceAll(' ', '\\s+')));
	}
});

test('mobile backend environment example matches runtime config default', () => {
	assert.match(envExample, /^EXPO_PUBLIC_FRAPPE_BASE_URL=http:\/\/127\.0\.0\.1:8000$/m);
	assert.match(configSource, /process\.env\.EXPO_PUBLIC_FRAPPE_BASE_URL/);
	assert.match(configSource, /http:\/\/127\.0\.0\.1:8000/);
	assert.match(readme, /\.env\.example/);
	assert.match(deliveryAudit, /apps\/mobile\/\.env\.example/);
});

test('mobile runtime gate is backed by installed dependency artifacts and verification notes', () => {
	assert.equal(existsSync(new URL('node_modules', mobileRoot)), true);
	assert.equal(existsSync(new URL('bun.lock', mobileRoot)), true);
	assert.match(deliveryAudit, /Mobile typecheck: `npm run typecheck`/i);
	assert.match(deliveryAudit, /Mobile startup: `npx expo start --localhost --port 8081`/i);
	assert.match(deliveryAudit, /Metro `Metro waiting on exp:\/\/127\.0\.0\.1:8081`/i);
	assert.match(deliveryAudit, /HTTP\/1\.1 200 OK` from `http:\/\/127\.0\.0\.1:8081`/i);
});

test('mobile generated runtime artifacts are ignored while lockfile remains trackable', () => {
	for (const ignoredPath of [
		'apps/mobile/node_modules/',
		'apps/mobile/.expo/',
		'apps/mobile/dist/',
		'apps/mobile/.metro/',
	]) {
		assert.match(gitignore, new RegExp(`^${ignoredPath.replaceAll('/', '\\/')}$`, 'm'));
	}
	assert.doesNotMatch(gitignore, /^apps\/mobile\/bun\.lock$/m);
});
