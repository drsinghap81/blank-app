# Trend Desk native apps (13 Nov 2026)

The web app in `docs/` stays the master copy. These are thin shells that open it, so every web update reaches the
phone and desktop apps without reinstalling. Built by `.github/workflows/native-apps.yml`; downloads on the
GitHub release **apps-latest**.

| Platform | Folder | Output | Notes |
|---|---|---|---|
| Android | `apps/mobile` (Capacitor 6) | `TrendDesk-android.apk` | Install directly ("install unknown apps" once). Play internal testing: add the keystore secrets → `TrendDesk-play.aab`. |
| iPhone | `apps/mobile` (Capacitor 6, iOS generated in CI) | build check only | TestFlight needs the Apple account secrets below. Until then use Safari → Share → Add to Home Screen. |
| Windows | `apps/desktop` (Electron 33) | `Trend Desk Setup x.y.z.exe` | Unsigned: SmartScreen asks once (More info → Run anyway). |
| Mac | `apps/desktop` | `Trend Desk-x.y.z.dmg` | Unsigned until the Apple account: right-click → Open the first time. |
| Linux | `apps/desktop` | `Trend Desk-x.y.z.AppImage` | |

## Turning on store builds (private testing)
- **Google Play internal testing** (Play Console account): create an upload keystore, then add repo secrets
  `ANDROID_KEYSTORE_B64` (base64 of the .jks), `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`.
  Upload `TrendDesk-play.aab` to an Internal testing track (up to 100 testers, no public listing).
- **Apple TestFlight** (Apple Developer account): create the app id `com.trenddesk.app` in App Store Connect, an App
  Store Connect API key, then add `APPLE_TEAM_ID`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8_B64`; the iOS job then
  gets an archive + upload step.

## Public later
A public listing needs: the store accounts in the owner's name, SEBI research-analyst position for showing
buy/sell setups to the public, store policy review for financial apps, and a build without the owner's live-order
server (order sending stays private).

## Limits of the shell apps
- Phone alerts (web push) work in the home-screen web app; inside the Android/iPhone shells they need native push
  (Firebase / APNs), not built yet.
- The PDF download uses the share sheet on phones; works in the shells through the same web code.
