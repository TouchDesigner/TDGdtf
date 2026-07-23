# TDGdtf — TouchDesigner GDTF Fixture Tool

## Project Context
TDGdtf parses [GDTF](https://gdtf.eu/gdtf) fixture files and builds a TouchDesigner component:
POP geometry per fixture geometry, DMX channel attributes, a filled-in DMX Fixture POP, and
custom parameters exposing all fixture features. The component persists its parsed state so it
restores after a TD restart without re-reading the GDTF file.

All Python runs inside TouchDesigner's embedded Python 3.x — prefer TD-native APIs
(`op()`, `tdu`, `parent()`, StorageManager) over desktop-Python patterns. No `import os`
path handling, no `__main__` guards.

## Architecture

```
src/TDGdtf/
├── core/           # TD-independent — runs and tests outside TouchDesigner
│   ├── parser.py   #   GDTFParser: pygdtf → TouchDesignerFixture (geometry grouping, channel merging)
│   ├── fixture.py  #   dataclasses + TypedDicts (ChannelTemplate schema, DMXChannelFunction, …)
│   └── utils.py    #   name sanitization (legalPopName, legalTdParName)
├── td/             # TouchDesigner-only (references project, tdu, op)
│   └── FixtureExt.py  # COMP extension: network builder, custom pars, fixture instances
└── tdgdtfFixture.tox  # packaged component
```

**Never let `core/` import TD APIs** (`tdu`, `op`, `project`). It is mypy-checked and testable
with plain Python; `td/` is where TD references live.

### How code loads in TD (important!)
- `FixtureExt` runs as a DAT inside the .tox — edits take effect on recompile immediately.
- `TDGdtf.core.*` are imported Python modules — TD caches them in `sys.modules`. After editing
  `core/*`, a TD restart (or `importlib.reload`, reloading `utils` before `parser`) is required.
  Symptom of a stale core with a fresh extension: inconsistent names/attributes that "should be
  impossible" from reading the source.

### Invariants — do not break
- **One sanitization point:** channel names are made TD-legal once, in the parser
  (`legalPopName`). `channel.name == tdChannelName ==` POP attribute name `==`
  `DmxChannels`/`DmxChannelsByType` keys `==` setter `channelName` arguments. Never add a
  second renaming step downstream; never use a raw GDTF name as a dict key or attribute.
- **Name rules:** POP attribute/group/node names must start with a letter, chars limited to
  `A-Za-z0-9_` → `legalPopName(name, prefix)` (`'geo'` for geometry/groups, `'ch'` for
  channels). Custom parameter names → `legalTdParName` (strips underscores, `Ch` prefix).
- **Generated operators are tagged** (tag `GDTFPARSER`); `_clearNetwork` destroys by tag.
  Anything `CreateNetwork` creates must carry the tag or it leaks on re-parse.
- **Persistence model:** channel template stored on parse; fixture/group values stored on
  structural changes and on project save (`PersistState`, wired to onProjectPreSave) — NOT on
  every value change. Don't add per-value-change storage writes; they run on every slider tick.

## Development workflow
- **`FixtureExt.py` is indented with TABS.** Match exactly — a mixed-indent edit breaks the DAT.
  After editing, compile-check: `python -m py_compile src/TDGdtf/td/FixtureExt.py`.
- **Testing core outside TD:** use a TouchDesigner build's Python
  (`C:\Program Files\Derivative\TouchDesigner.<build>\bin\python*.exe`) with `pygdtf` installed
  and `src` on `PYTHONPATH`. The repo `.venv` may point at an uninstalled TD build — verify
  before relying on it.
- **Type checking:** `python -m mypy` (configured in `pyproject.toml`, covers `core/` only).
  TD types in `td/` come from `tdi` under `TYPE_CHECKING` — never import `tdi` at runtime.
- **Sample fixtures** in `gdtfSampleFiles/`. Edge cases: Chauvet Color Strike M "68Ch Mode" has
  digit-leading geometry names (`68ch_…`), attribute names with spaces (`FX Dimmer`), and
  `1/2`-style compound names that defeat sequential grouping.
- **Releases:** bump `__version__` in `src/TDGdtf/__init__.py` (pyproject reads it), commit,
  tag `v<version>` (must match exactly), push commit + tag. See README → Releasing.

## Conventions
- Operators: camelCase, meaningful names, type prefix when it helps (`script_pointChannels`,
  `table_pointMaster`). No default names like `base1`.
- Python: camelCase variables/functions, ALLCAPS constants. Extension methods: promoted start
  with a Capital (`Parse`, `SetDmxValue`), internal start lowercase/underscore (`_clearNetwork`).
- State: StorageManager via the `stored` items in `FixtureExt.__init__`; ad-hoc storage uses
  namespaced keys (`'config/bpm'`). No global Python variables — lost on recompile.
- Logging: use the module `logger` / `self._log` (per-comp child logger) → writes to
  `tdgdtf_fixture.log` in the project folder. No bare `print` in committed code.
- Docstrings on public methods; comments only for constraints the code can't show.

## What NOT to do
- No `time.sleep()` — blocks the cook thread.
- No hardcoded absolute paths — use `project.folder`, `app.samplesFolder`.
- No UI changes from non-main threads.
- Don't create operators outside the tagged `CreateNetwork` flow; network-level scaffolding
  (the fixture POP, master tables, script POPs) lives in the .tox, not in Python.
- Don't rename the `Modes` custom parameter or other pars wired into `tdgdtfFixture.tox`
  without a coordinated .tox edit.

## References
- TouchDesigner docs: https://docs.derivative.ca
- Offline help: file:///C:/Program Files/Derivative/TouchDesigner.2025.33025/Samples/Learn/OfflineHelp/https.docs.derivative.ca
- tdi (typing lib): file:///C:/Program Files/Derivative/TouchDesigner.2025.33025/bin/Lib/tdi
- GDTF spec: https://www.gdtf.eu/gdtf
- pygdtf: https://pypi.org/project/pygdtf/
