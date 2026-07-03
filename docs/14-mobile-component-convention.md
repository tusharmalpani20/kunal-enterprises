# Mobile Component Convention

Goal 3 asked for `react-native-reusables` components unless the app setup proved a better local convention.

During dependency verification, the package named `react-native-reusables` was not available as a published runtime package. The installable package is `@react-native-reusables/cli`, which is included in `apps/mobile/package.json` as a development dependency. Because there is no stable runtime component package to import, the mobile app uses a local component convention built on React Native primitives and `lucide-react-native`.

## Current Convention

| UI need | Implementation |
| --- | --- |
| Shell and page layout | `SafeAreaView`, `ScrollView`, and `View` in `apps/mobile/app/index.tsx`. |
| Buttons and rows | `Pressable` with stable shared styles such as `modeButton`, `utilityButton`, `rowButton`, `primaryAction`, and `iconButton`. |
| Inputs | `TextInput` with shared `input` and `fieldLabel` styles. |
| Reusable workspace framing | Local `Workspace` component in `apps/mobile/app/index.tsx`. |
| Reusable list row | Local `RowButton` component in `apps/mobile/app/index.tsx`. |
| Icons | `lucide-react-native` icons for history, profile, logout, add/remove, search, product group, stock, cart, and success actions. |
| Domain behavior | Pure domain modules in `apps/mobile/src/domain/*.mjs`, with UI passing state through the public mobile API boundary. |

## Decision

The app keeps `@react-native-reusables/cli` available for future component scaffolding, but does not import a nonexistent `react-native-reusables` runtime package. This avoids pinning production UI to an unavailable dependency while preserving the reusable component intent through local primitives, shared styles, and small local components.

If a stable runtime package becomes available later, migrate incrementally by replacing `Workspace`, `RowButton`, and shared button/input styles first. The public behavior tests should remain unchanged during that migration.
