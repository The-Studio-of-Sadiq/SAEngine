# SAEngine UI translations

SAEngine's own screens (everything under `src/vs/**/saengine*/`, the SAEngine strings in
rebranded Code-OSS files, and the `theme-saengine` extension) can be shown in Bangla.
The rest of the Code-OSS workbench (menus, Explorer, settings, ...) stays in English:
there is no free, licensed Bangla translation of Code-OSS in this repository, and nothing
is downloaded.

## How it works

Code-OSS translates through *language pack* extensions. A pack contributes
`localizations` in its `package.json`; for the core (`"id": "vscode"`) it ships a
`main.i18n.json` with translations keyed by module id and NLS key:

```json
{ "contents": { "vs/workbench/contrib/saengineProject/browser/startEditor": { "start.title": "শুরু" } } }
```

On start-up the shared process (`LocalizationsUpdater` → `NativeLanguagePackService`)
lists the installed extensions, built-in ones included, and writes `languagepacks.json`
in the user data folder. *Configure Display Language* offers every language found there
and writes the choice to `argv.json` (`"locale": "bn"`). On the next start the main
process (`src/vs/base/node/nls.ts`) merges the pack with the build's `out/nls.keys.json`
and `out/nls.messages.json` into a cached message table; every string the pack does not
translate falls back to English.

SAEngine ships Bangla as the **built-in extension**
`extensions/saengine-language-pack-bn`. This is the simplest way that:

- works offline and ships inside the installer, like every other folder in `extensions/`
  (the extension gallery is not used and may be disabled);
- needs no change to the workbench code, so it cannot conflict with other work;
- uses the same module id / key pairs as the build's NLS step, because the extractor
  calls the build's own analyser (`build/lib/nls-analysis.ts`).

Language packs are applied only in a **built** product (one with a commit and
`out/nls.keys.json`); `VSCODE_DEV=1` runs always show English, by design of Code-OSS.
To try the pack, build the product (or copy the pack folder into a packaged
`resources/app/extensions/`), run *Configure Display Language*, pick বাংলা and restart.

## Files

| File | Who edits it |
| --- | --- |
| `extract-strings.ts` | Extracts the strings and regenerates the pack. |
| `bn/strings.bn.json` | **Translators.** One entry per string: `en` (source, do not edit), `bn`, `status`, optional `note` and `comment`. |
| `bn/glossary.bn.md` | **Translators.** Term choices; add a term before using it. |
| `extensions/saengine-language-pack-bn/translations/*.i18n.json` | Generated; do not edit. |

`status` is `translated`, `review` (a translator should check it; `note` says why) or
`untranslated` (shown in English). `review` strings are shown in Bangla meanwhile.

## Workflow

```sh
cd workbench
node build/saengine/i18n/extract-strings.ts           # after UI changes: add new strings, regenerate the pack
node build/saengine/i18n/extract-strings.ts --check   # CI / before a commit: fails if anything is out of date
```

New strings arrive as `untranslated`. When the English of a translated string changes, it
keeps its Bangla text but goes back to `review` with the old English in `note`.
`src/vs/workbench/contrib/saengineProject/test/node/bnLanguagePack.test.ts` checks that every
entry has Bangla or is marked untranslated, that placeholders match, that the pack is in
sync with the table, and that the pack loads through the NLS resolver.

The reports and drawings are written by the Python backend in the project's language (Project
Settings › Project › Language); their labels have their own catalogue,
`python/src/saengine/i18n/bn.json` (see `saengine/i18n/__init__.py`). Project Settings also
offers to switch the display language to the project's (it calls the workbench's locale service,
which writes `argv.json` and restarts). Other Python messages (problems, warnings, progress) stay
in English.
