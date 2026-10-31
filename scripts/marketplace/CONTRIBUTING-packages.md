# Contributing a package

This is the CONTRIBUTING of the SAEngine package repositories (`saengine-design-codes`,
`saengine-structure-templates`, `saengine-building-templates`); the owner copies it into each
as `CONTRIBUTING.md`. The package format is described in SAEngine's `docs/packages.md` and, for
design code tables, `docs/code-packs.md`.

## Adding or changing a package

1. One folder per package, named as its `id`: `<id>/pack.json` and its files.
2. Start from a skeleton: `saengine codepack new <id> --dest .` (design codes), or copy an
   existing template package of the same kind.
3. Give it a `licence` (SPDX): `CC-BY-4.0` for data and templates, `AGPL-3.0-only` for packages
   with `hooks.py` (code that runs inside SAEngine). Give it an `author` and a short
   `description`; a `preview` image (PNG, at most 256 KB and 1024 px) for the store card.
4. Cite the source of every value: for a design code, the clause, table and page of the code
   (`sources` in pack.json and in each table). Never copy tables you have no right to publish.
5. Check it: `saengine codepack validate <id> --kind <kind>` must say `ok`.
6. A changed package needs a new `version` (SemVer). Released versions are never changed.
7. Open a pull request. CI validates every changed package; a maintainer reviews and merges;
   a `packages-*` tag publishes the zips and the signed index.

## What is refused

- programs and scripts (`.exe`, `.dll`, `.pyd`, `.bat`, `.ps1`, `.cmd`, `.js`...), links, files
  over 5 MB (50 MB for a `.civil`);
- in a building template: results, a soil report, exported deliverables or the version history;
  a site located more precisely than a town; names on drawings or project files other than the
  package's author. Templates never hold client data.

## Review rules for packages with code

A package with `hooks.py` (design-code hooks, or coded structure templates) runs Python on the
engineer's computer once trusted, so:

- it needs a second reviewer: CODEOWNERS lists the maintainers for every such package, and
  branch protection requires their review;
- the reviewer reads every `.py` file of the package and checks that it only computes: no file,
  network, process or environment access (`open`, `os`, `subprocess`, `socket`, `urllib`,
  `importlib`, `ctypes`, `eval`, `exec`, `__import__`...), no imports beyond the Python standard
  library's `math`, `dataclasses`, `typing` and `saengine` itself;
- a coded template's function takes only its parameters and returns geometry; its parameters
  have `minimum` and `maximum` where a large value could make a huge model;
- the index records the hash of the reviewed code (`hooksSha256`), which SAEngine shows before
  installing. Any change to a `.py` file is a new version and a new review.

## Mirrors

`bnbc2020`, `saengine-shapes` and `saengine-default-building` are developed in SAEngine and
mirrored here by `scripts/marketplace/mirror_packages.py`; do not edit them here (CI refuses a
mirror that differs from its SAEngine commit). Change them in SAEngine instead.
