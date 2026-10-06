import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const appConfig = JSON.parse(readFileSync(new URL('../app.json', import.meta.url), 'utf8'));
const authShellSource = readFileSync(new URL('../src/components/AuthShell.tsx', import.meta.url), 'utf8');
const profileSource = readFileSync(new URL('../app/(app)/profile.tsx', import.meta.url), 'utf8');
const appVersionSource = readFileSync(new URL('../src/constants/appVersion.ts', import.meta.url), 'utf8');
const androidGradle = readFileSync(new URL('../android/app/build.gradle', import.meta.url), 'utf8');
const iosInfoPlist = readFileSync(new URL('../ios/KunalEnterprises/Info.plist', import.meta.url), 'utf8');

test('mobile app metadata is version 0.1.2 with incremented build numbers', () => {
  assert.equal(packageJson.version, '0.1.2');
  assert.match(appVersionSource, /APP_VERSION = '0\.1\.2'/);
  assert.match(androidGradle, /versionName "0\.1\.2"/);
  assert.match(androidGradle, /versionCode 3\b/);
  assert.equal(appConfig.expo.version, '0.1.2');
  assert.equal(appConfig.expo.android.versionCode, 3);
  assert.equal(appConfig.expo.ios.buildNumber, '3');
  assert.match(iosInfoPlist, /<key>CFBundleShortVersionString<\/key>\s*<string>0\.1\.2<\/string>/);
  assert.match(iosInfoPlist, /<key>CFBundleVersion<\/key>\s*<string>3<\/string>/);
});

test('Android uses system-bar-safe non-edge-to-edge configuration', () => {
  assert.equal(appConfig.expo.android.edgeToEdgeEnabled, false);
  assert.deepEqual(appConfig.expo.androidStatusBar, {
    backgroundColor: '#ffffff',
    barStyle: 'dark-content',
    translucent: false,
  });
});

test('Login and Profile surfaces include the shared version footer', () => {
  assert.match(authShellSource, /<AppVersionFooter \/>/);
  assert.match(profileSource, /<AppVersionFooter \/>/);
});
