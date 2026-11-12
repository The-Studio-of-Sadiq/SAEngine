# Store sites of the package repositories

Each marketplace repository gets its own static store site on GitHub Pages
(docs/marketplace-plan.md §5, round M3):

| Repository | Site (once Pages is on) |
| --- | --- |
| `saengine-design-codes` | `https://the-studio-of-sadiq.github.io/saengine-design-codes/` |
| `saengine-structure-templates` | `https://the-studio-of-sadiq.github.io/saengine-structure-templates/` |
| `saengine-building-templates` | `https://the-studio-of-sadiq.github.io/saengine-building-templates/` |
| `saengine-index` | `https://the-studio-of-sadiq.github.io/saengine-index/` (every package, from `index.json`) |

The site is a catalogue: a card per package and a page with its kind, version, author, licence,
requirements, preview and the SHA-256 of its zip. Installing stays in SAEngine (≡ › Packages... ›
Browse), which verifies the signed index and every download.

## Files

- `build_store.py`: builds the site from a repository checkout (`<id>/pack.json` folders) and/or
  an `index.json`. Standard library only; run it with `python -I`.
- `store-pages.yml`: the workflow. It builds the site on every push to `main`, on a release and
  on demand, and force-pushes it as the single commit of an **orphan** `gh-pages` branch (no
  shared history with `main`).

## Setting it up (owner)

For each of the four repositories:

1. Copy `store-pages.yml` to `.github/workflows/store-pages.yml` and `build_store.py` to
   `.github/store/build_store.py` (one pull request per repository).
2. After it is merged, run the workflow once (Actions › Store site › Run workflow): it creates
   the orphan `gh-pages` branch.
3. Enable Pages: Settings › Pages › Build and deployment › *Deploy from a branch* ›
   `gh-pages` / `(root)`.

Try it locally:

```console
python -I scripts/marketplace/store-site/build_store.py --repo ../saengine-design-codes --out _site
```
