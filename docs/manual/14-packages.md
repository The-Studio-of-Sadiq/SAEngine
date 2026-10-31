# Packages: design codes and templates

Packages add to SAEngine without changing the program. There are three kinds:

| Kind | What it gives | Where it is used |
| --- | --- | --- |
| Design code | a code as data: locations and hazards, loads, combinations, coefficients, materials, factors, detailing limits, MEP tables, each with its clauses | 02 Project Settings › Design code |
| Structure template | presets of the parametric shapes (trusses, arches, domes, vaults, cable nets), and new shape kinds made by the package's own code | the modeller's Generate panel |
| Building template | a building specification, or a whole project to start from | New Building from Grid, New Project from Template... |

BNBC 2020, the shape presets (*SAEngine shapes*) and the default building (*Dhaka 6-storey
residential, 3 × 2 bays*) are built in. The file formats, the command line and the safety rules
are in [docs/packages.md](../packages.md).

## The Packages page

Open it from **≡ › Packages...** (or the Command Palette: *SAEngine: Packages...*). Its tabs:

- **Installed**: every package on this computer, grouped *Built-in*, *Your Packs* (for every
  project) and *This Project* (design codes kept in `02 Project Settings/code-packs`, which travel
  with the project and its `.civil` archive). Select one to see its details: version, author,
  licence, what it provides, its problems and its hooks. **Validate** checks a package's folder;
  **Remove...** deletes a package of yours or of the project (built-in ones cannot be removed;
  install your own copy of the same id to replace one).
- **Browse**: the packages published for SAEngine. The list is signed: SAEngine checks its
  signature before it shows it. Select a package and choose **Install**; a design code asks
  whether it is for you or for this project, templates are installed for you. The download is
  checked against the SHA-256 in the signed list before it is installed.
- **Updates**: your packages with a newer published version. Updating a design code of this
  project asks first, because loads and design results may change; run **Run All** again
  afterwards. The report records the version of the design code used.

The chips above the list show one kind only. **Install from File...** installs a package folder
or `.zip` you were given, or opens an *offline bundle* (below). **Installer Components...** lists
the optional programs of the setup (EnergyPlus, LibreCAD, LibreDWG, the AI assistant, Git,
collaboration).

The list of published packages is read when the page opens and at most once a day in the
background (a notification says when your packages have updates). Turn both off with the setting
**SAEngine › Packages: Check Online**; the page then shows the last list it saw.

## Packages that contain code

A design code may carry *hooks* (Python that replaces a design function) and a structure template
may carry *coded templates* (Python that makes a new shape). Installing such a package never runs
its code. The page marks it **contains code**; read its `hooks.py` (Open pack.json shows the
folder) and choose **Trust This Package's Code...** only if you know who wrote it. Trusted code
runs with your permissions. Changing any `.py` file of the package withdraws the trust.

## Using templates

- **Generate panel** (05 Floor Plan › modeller, *Generate Shape...*): the list *Start from a
  structure template...* shows the presets of every structure template installed, grouped by
  package. A preset fills the form; change the values, check the preview and **Insert**. A coded
  template shows its own form; it makes geometry only when its package is trusted.
- **New Building from Grid**: the row *Start from* lists the building specifications installed.
  The wizard opens with the built-in *Dhaka 6-storey residential* and you can switch at any time;
  the name you typed is kept.
- **New Project from Template...** (start page, File menu, ≡): opens a whole project from an
  installed full building template, as a new project in a folder you choose. SAEngine checks it
  first: a template holds inputs only (no results, no soil report, no exported deliverables, no
  version history), places the site no more precisely than a town and names no one but its
  author.

## Offline

Offices with a slow connection can get everything as one file: the *offline bundle*
(`saengine-packages-offline-<date>.zip`, attached to each release of the package index). Choose
**Install from File...** and pick the bundle: Browse then lists its packages, and **Install**
copies them from the bundle with the same signature and SHA-256 checks. **Published List** in the
status line returns to the online list. A single package `.zip` from a colleague installs the same
way; it is labelled as yours, not as published.

## Limits in this version

- A design code package gives the site and hazard values, loads, combinations and coefficients;
  resistance factors and detailing limits of member design are still BNBC 2020's.
- Release builds accept only the owner's signing key, which is not published yet: until it is,
  Browse in a release build says the list cannot be checked. Development builds accept a test key.
- Community packages (published by others) are not listed yet; only the official repositories are.
- Components are added by running the SAEngine setup again; downloading a single component waits
  for SAEngine to be code-signed.
