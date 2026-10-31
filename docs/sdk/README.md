# SAEngine SDK

SAEngine can be driven and extended from outside the app in four ways. All of them reuse what
the app itself uses; there is no second engine.

| Way | For | Where |
| --- | --- | --- |
| **Python API** (`saengine.api`) | scripts, notebooks, other Python programs | [reference.md](reference.md#python-api-saengineapi) |
| **JSON-RPC** (`python -m saengine.rpc.server`) | programs in any language; the app's own backend | [reference.md](reference.md#json-rpc-methods) |
| **Command line** (`saengine ...`) | batch runs, CI, scheduled jobs | [docs/cli.md](../cli.md) |
| **Packages** with hooks | new design formulas and new shape kinds inside the app | [below](#hooks-code-inside-saengine), [docs/packages.md](../packages.md) |

AI assistants connect through the MCP server described in [docs/ai-assistants.md](../ai-assistants.md).

## Versioning

- The **Python API** is `saengine.api`: only the names in its `__all__` are public.
  `saengine.api.API_VERSION` (now **1.0.0**) follows SemVer: a minor version adds names or
  optional parameters; a major version may change or remove them, and the release notes say
  how to move. Everything else under `saengine.*` is internal and may change in any release.
- The **JSON-RPC methods** are versioned with SAEngine itself: a method's name and its required
  parameters stay; new optional parameters and new fields in answers may appear in any release,
  so clients must ignore fields they do not know. `saengine/info` returns the versions of the
  backend stack.
- The **package format** is `saengine.codePack/1` (`pack.json`); the package index is
  `saengine.packageIndex/1`. A package states the SAEngine it needs in `requires.saengine`.
- The reference is generated from the code (`scripts/docs/gen_sdk_reference.py`) and a test
  fails when it is out of date, so it always matches the release it ships with.

## Python API

Install SAEngine (its setup bundles Python with `saengine`), or install the `python/` folder of
the repository into your own environment (`pip install -e python`). Then:

```python
from saengine import api

print(api.API_VERSION)
for pack in api.list_packages(kind=None):          # every package, every kind
    print(f"{pack.id:24} {pack.kind:18} {pack.scope:8} {pack.version or ''}")

spec = api.BuildingSpec(gridsX=[6000, 6000], gridsY=[5000], storyCount=4)
parts = api.generate_building(spec)                 # floor plan, objects, materials, settings
print(parts["summary"])
```

More in [examples/](examples/): `list_packages.py`, `new_building.py`, `rpc_client.py` and a
package with a coded template, `portal-frames/`.

## JSON-RPC

`python -m saengine.rpc.server` reads JSON-RPC 2.0 requests from stdin and writes the answers to
stdout, each framed as in the Language Server Protocol:

```
Content-Length: 58\r\n
\r\n
{"jsonrpc":"2.0","id":1,"method":"codes/list","params":{}}
```

Every method and its parameters are in [reference.md](reference.md#json-rpc-methods). Paths are
absolute; a project is named by its folder (`root` or `projectRoot`). A refused operation
answers `{ "ok": false, "message", "problems" }` rather than an error, so a client can show the
engineer why. [examples/rpc_client.py](examples/rpc_client.py) is a complete client in 60 lines.

## Hooks: code inside SAEngine

A package may carry Python (`"hooks": "hooks.py"` in `pack.json`). SAEngine never runs it until
the engineer trusts that exact code on the Packages page; any change to a `.py` file of the
package withdraws the trust. Hooks run inside SAEngine's backend with the engineer's permissions,
so the package repositories review them (`scripts/marketplace/CONTRIBUTING-packages.md`).

**Coded structure templates** (new shape kinds). A structure template file names a `generator`,
a top-level function of `hooks.py`:

```python
def portal(params: dict) -> dict:
    span, height = params["span"], params["height"]          # mm, checked against the schema
    return {
        "members": [
            {"start": [0, 0, 0], "end": [0, 0, height], "type": "MEMBER"},
            {"start": [0, 0, height], "end": [span, 0, height], "type": "MEMBER"},
            {"start": [span, 0, height], "end": [span, 0, 0], "type": "MEMBER"},
        ],
        "supports": [{"at": [0, 0, 0], "fixity": "fixed"}, {"at": [span, 0, 0], "fixity": "fixed"}],
    }
```

It receives only its own parameters (validated against the template's `parameters` schema;
`origin` and `rotation` are applied by SAEngine afterwards) and returns the geometry, as a
`saengine.api.Geometry` or its JSON. It should compute only: no files, network or processes. The
Generate panel shows the form made from the schema, previews the result and inserts it like a
built-in shape. Test it without the app:

```python
from saengine import api
print(api.coded_geometry("portal-frames", "templates/portal.json", {"span": 15000}))
```

(after `api.install_package(<folder>)` and `api.trust_package("portal-frames", True,
kind="structureTemplate")`).

**Design-code hooks** (formulas). A design code's `hooks.py` may define functions that replace
SAEngine's functions of the same name ([docs/code-packs.md](../code-packs.md#data-or-formula-hooks-and-trust)).
The registry finds, trusts and loads them (`api.load_package(id).hook(name)` returns the trusted
function or `None`), but in this version no member-design function consults hooks yet; the
design formulas stay SAEngine's (BNBC 2020). Write data packs for now, and hooks only for coded
templates.

## Command line

`saengine` runs the same operations headless: `validate`, `run-all`, `derive`, `analyse`,
`design`, `report`, `check`, `status`, `export`, `import`, `new-building` and `codepack`
(`list`, `show`, `new`, `validate`, `diff`, `install`, `remove`). Every command takes `--json`
for one machine-readable document on stdout. See [docs/cli.md](../cli.md).
