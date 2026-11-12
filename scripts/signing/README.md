# Code signing with SignPath (round M7, waiting for the owner)

SAEngine is not code-signed yet, so Smart App Control and SmartScreen block or warn about its
setup. SignPath Foundation signs open-source projects for free; the repository is public, so it
qualifies. Everything in SAEngine is ready for it except the sign-up, which only the owner can do.

What is ready:

- `signpath-release-steps.yml`: the steps to paste into `.github/workflows/release.yml` in place
  of "Code signing (not yet)". They upload the unsigned setup as an artifact, ask SignPath to sign
  it and download the signed setup before its `.sha256` is written.
- The app checks the signature (`platform/saengine/node/authenticode.ts`): once product.json has
  `"saengineSigning": { "publisher": "<the certificate's CN>" }`, *Add Component...* runs a setup
  only when Windows reports a **valid** Authenticode signature by that publisher (on top of the
  release's SHA-256). Without the setting it checks the SHA-256 only, as today.
- Component zips: `scripts/installer/component_zips.py` builds
  `SAEngine-<version>-component-<name>.zip` and `SAEngine-<version>-components.json` from the
  built app folder. By decision D7 the app downloads no program until SAEngine is signed, so the
  zips are published but offered by the app only after signing.

What the owner must do:

1. Apply at <https://signpath.org> for the SignPath Foundation open-source programme with the
   repository `The-Studio-of-Sadiq/SAEngine` (project slug `SAEngine`, artifact configuration
   for an Inno Setup `.exe`, signing policy `release-signing`).
2. In the repository settings add the secret `SIGNPATH_API_TOKEN` and the variable
   `SIGNPATH_ORGANIZATION_ID` (values from SignPath).
3. Replace the "Code signing (not yet)" step of `release.yml` with `signpath-release-steps.yml`.
4. Put the certificate's publisher name in `workbench/product.json`:
   `"saengineSigning": { "publisher": "SignPath Foundation" }` (or the CN SignPath issues).
5. Add `python -I scripts/installer/component_zips.py --app <app folder> --version <version>
   --out dist` to the release after the build and upload its files as release assets.
