# TDGdtf

A TouchDesigner tool that parses [GDTF](https://gdtf-share.com) fixture files and builds component networks with POP geometry, DMX channel attributes, and a full parameter UI.

Once a fixture is loaded, the component can be used to control all fixtures of that type present in a setup. The first input of the component should be a Point POP with the number of points equaling the number of fixtures of this type in the installation. A limiting factor is that all the fixtures should also be using the same DMX Mode. If the same fixture is present multiple times, but running with different DMX Modes, extra TDGdtf fixture components are required.

To deal with fixture addressing, the Point POP can use the Point attributes:
* `DMXFixtureNet`
* `DMXFixtureSubnet`
* `DMXFixtureUniverse`
* `DMXFixtureChannel`
* `DMXFixtureNetAddress`

to control the DMX addressing of the individual fixtures.

To connect the fixtures to a DMX Out POP, reference the internal DMX Fixture POP called "fixture".

The parameters to control the fixture are automatically created and by default all fixtures of that type are controlled via these parameters at the same time. You can control individual fixtures by selecting them via the `Control Target` parameter on the "Channel Functions" page.

Individual control is also possible via setting existing point or primitive attributes. This can be done by using the TDGdtf component's first output, modifying an existing attribute and wiring it back into the second input of the component. While a bit untraditional, this allows all manipulations to happen outside the component without having to make any changes internally.

A range of Python methods exists to create groups and set channel function values for all fixtures, individual fixtures, or fixture groups. All available methods are listed below. This can get a bit heavy for larger setups, so controlling fixtures via attributes is the intended and preferred way of working.

## Setup

### Installation

Install the package into a Python virtual environment used by TouchDesigner (e.g. one
managed by TD's Python Environment Manager). The package is not on a public index, so
install straight from GitHub (or from a local clone with `pip install <path>`):

```bash
pip install git+https://github.com/TouchDesigner/TDGdtf.git
```

The packaged component (`tdgdtfFixture.tox`) ships inside the package. To load it, create
a **Base COMP** and set its **External .tox** parameter to the packaged file using an
expression:

```python
mod.TDGdtf.toxPath('TDGdtfFixture')
```

### Creating a fixture component

1. Set the **Gdtffile** parameter on the component to point at a `.gdtf` file.
2. Press **Parse** to read the file, build the operator network, and create channel parameters (or call `Parse()` from Python).
3. Use the **Modes** property or the mode menu parameter to switch DMX modes.



### State persistence

All parsed data — the channel template, fixture instances, groups, and channel values — is persisted via TouchDesigner's StorageManager, so the component fully restores its state after a project restart without re-reading the GDTF file. The channel template is stored when a file is parsed; fixture and group values are written on structural changes (adding/removing fixtures or groups) and automatically on project save via `PersistState()`. Channel value changes between saves are not persisted individually, so state on disk always reflects the last project save.

### Parsing behavior

- The currently selected DMX mode is preserved by name when re-parsing; if the new file has no mode with that name, the first mode is used.
- Consecutive channels sharing a GDTF ActivationGroup (e.g. `ColorAdd_R/G/B`) are merged into one multi-component vector channel — but only when all channels have the same bit depth and exactly one channel function each. Incompatible channels (e.g. a 16-bit `Gobo1Pos` next to an 8-bit `Gobo1PosRotate`) stay separate, since a DMX channel block cannot mix bit depths and a vector component cannot expose its own function menu.
- GDTF *virtual* channels (channels without a DMX offset) have no DMX footprint and are skipped with a warning.
- Channels whose attribute is missing from the fixture's attribute list are kept but logged as a warning, and are never merged with neighbouring channels.
- Channel names are sanitized into TD parameter names; if two different attributes sanitize to the same parameter name, a warning is logged and only the first one gets parameters.
- POP attribute and group names must begin with a letter, so geometry and channel names are sanitized: characters outside `A-Za-z0-9_` become underscores, and names starting with a digit or underscore (e.g. the `68ch_...` geometries of the Chauvet Color Strike M) are prefixed with `geo` (geometry/group names) or `ch` (channels). Channels are renamed at parse time (each rename is logged), so the same TD-legal name is used consistently everywhere: POP attribute names, `DmxChannels`/`DmxChannelsByType` keys, setter `channelName` arguments, and parameter labels.

### Logging

The component writes structured logs to `tdgdtf_fixture.log` in the project folder. Every record is tagged with the path of the component that produced it (or `core` for records from the parser modules). The file logs at DEBUG level and includes parse timings, state restores, and all warnings described above.

---

## Promoted API Reference

All promoted functions are accessed via `op('yourComp').FunctionName(...)`.

### Parsing & Network

| Method | Description |
|---|---|
| `Parse()` | Parse the GDTF file set in the **Gdtffile** parameter and build the operator network. Preserves the currently selected mode by name; falls back to the first mode if no match exists in the new file. |
| `CreateNetwork(dmxMode=None)` | Rebuild the operator network for a specific DMX mode. Called automatically by `Parse()` and the `Modes` setter. |
| `Reset()` | Reset the component to an empty state: destroy the generated network, remove all channel parameters, and clear runtime and persisted fixture data (fixtures, groups, values, modes). The **Gdtffile** parameter is left untouched. |

### Methods

| Method | Description |
|---|---|
| `DmxChannel(name)` | Return the `tdu.Dependency` for a single channel by name, or `None` if not found. |
| `GetDmxChannelValues(name)` | Return a flat list of DMX values for a channel across all groups and fixtures. |
| `PersistState()` | Write the current fixture and group values to storage. Called automatically on project save; call it manually to snapshot state at any other time. |

### Properties

| Property | Type | Description |
|---|---|---|
| `Modes` | get/set | Get the current `DMXModeInfo` object, or `None` when no fixture is loaded (e.g. after `Reset()`). Assign a TD menu parameter value (with `.menuIndex`) to switch modes and rebuild the network; assignments are ignored while no fixture is loaded. |
| `DmxChannels` | dict (read-only) | Dict of `{channelName: tdu.Dependency}`. See [Retrieving Values](#retrieving-values) for the dependency value shapes. |
| `DmxChannelsByType` | dict (read-only) | Dict with `'point'` and `'primitive'` keys, each a deduplicated list of attribute names by geometry type. |
| `MasterControlledChannelsByType` | dict (read-only) | Same shape as `DmxChannelsByType` but filtered to channels whose GDTF `LogicalChannel.master` is `"Grand"`. Channels with `"Group"` or `"None"` master are excluded. |

---

### Fixture Management

#### `AddFixture(label='')`
Create a new fixture instance. Returns the fixture ID (`int`, lowest available).

```python
fid = op('yourComp').AddFixture('Stage Left')
# fid = 0
```

#### `RemoveFixture(fixtureId)`
Remove a fixture instance by its ID.

```python
op('yourComp').RemoveFixture(0)
```

#### `SetFixtureCount(count)`
Add or remove fixture instances to reach the desired total count. When removing, the highest IDs are removed first. Menus, storage, and dependencies are refreshed once at the end, so this is the efficient way to create many fixtures.

```python
op('yourComp').SetFixtureCount(8)
```

#### `GetFixtures()`
Return a list of dicts describing all current fixture instances.

```python
op('yourComp').GetFixtures()
# [{'fixtureId': 0, 'label': 'Stage Left', 'index': 0},
#  {'fixtureId': 1, 'label': '',            'index': 1}]
```

#### `GetFixture(identifier)`
Return the info dict for a single fixture, or `None` if not found. Pass an `int` to look up by fixture ID, or a `str` to look up by label (first match).

```python
op('yourComp').GetFixture(0)
# {'fixtureId': 0, 'label': 'Stage Left', 'index': 0}

op('yourComp').GetFixture('Stage Left')
# {'fixtureId': 0, 'label': 'Stage Left', 'index': 0}

op('yourComp').GetFixture(99)
# None
```

---

### Group Management

Groups are named collections of fixture IDs. They can be used as targets when setting values.

#### `CreateGroup(name, fixtureIds)`
Create or replace a named group containing the given fixture IDs.

```python
op('yourComp').CreateGroup('front', [0, 1, 2])
```

#### `DeleteGroup(name)`
Delete a named group.

```python
op('yourComp').DeleteGroup('front')
```

#### `GetGroups()`
Return a dict of all groups: `{groupName: [fixtureId, ...]}`.

```python
op('yourComp').GetGroups()
# {'front': [0, 1, 2], 'back': [3, 4]}
```

---

### Setting Values

All setter methods accept a `target` parameter that controls which fixture instances are affected:

| Target value | Meaning |
|---|---|
| `'all'` (default) | All fixture instances |
| `int` or `'3'` | A single fixture by ID |
| `'groupName'` | All fixtures in a named group |
| `'0,2,front'` | Comma-separated mix of IDs and group names |

`channelName` may be an attribute name (updates the channel in all geometry groups) or a group-qualified unique name like `'body_beam_Dimmer'` (updates one group only).

> **Note:** `SetDmxValue` and `SetNormalizedValue` currently write only the first component of a channel. Multi-component channels (e.g. merged RGB vectors) can be fully set through the generated custom parameters, or per fixture via POP attribute lookups — modify the channel's attribute on the component's first output and wire it back into the second input, as described in the introduction.

#### `SetDmxValue(channelName, value, target='all')`
Set the raw DMX integer value on a channel.

```python
op('yourComp').SetDmxValue('Pan', 128)
op('yourComp').SetDmxValue('Pan', 200, target='front')
op('yourComp').SetDmxValue('Tilt', 50, target=2)
```

#### `SetNormalizedValue(channelName, value, target='all')`
Set a normalized 0–1 value on a channel. Only valid for channels marked as normalized in the GDTF fixture definition — logs a warning and no-ops if the channel is not normalized.

```python
op('yourComp').SetNormalizedValue('Dimmer', 0.5)
op('yourComp').SetNormalizedValue('Dimmer', 1.0, target='front')
```

#### `SetFunction(channelName, functionIndex, target='all')`
Set the active channel function by its menu index. This switches which function is controlling the channel (e.g. switching between different gobo wheels).

```python
op('yourComp').SetFunction('Gobo1', 1)
```

#### `SetFunctionValue(channelName, value, target='all')`
Set a physical function value (in the function's physical units). The value is automatically converted to the corresponding DMX value based on the current channel function's physical-to-DMX mapping. Channel functions with a zero-width physical range map to the start of their DMX range.

```python
op('yourComp').SetFunctionValue('Pan', 180.0)
op('yourComp').SetFunctionValue('Pan', 90.0, target='front')
```

#### `SetChannelSet(channelName, channelSetIndex, target='all')`
Set the active channel set (preset) by its menu index within the current channel function.

```python
op('yourComp').SetChannelSet('Color1', 3)
```

---

### Retrieving Values

#### `DmxChannel(name)`
Return the `tdu.Dependency` object for a single channel, or `None` if the channel name is not found. Because these are `tdu.Dependency` objects, any operator expression referencing `.val` automatically re-cooks when the values change.

The shape of `.val` depends on the channel:

| Channel | `.val` shape |
|---|---|
| Single geometry group | `[valuePerFixture, ...]` — one entry per fixture instance |
| Multiple geometry groups (same attribute) | `{geoGroup: [valuePerFixture, ...]}` |

Each per-fixture value is in turn:

| Channel kind | Per-fixture value |
|---|---|
| Single component | scalar — `float` (0–1) if normalized, `int` (raw DMX) otherwise |
| Multi-component (e.g. RGB) | tuple, e.g. `(1.0, 0.5, 0.0)` |
| Sequential geometry (n instances) | list of n values, one per geometry member |

```python
dep = op('yourComp').DmxChannel('Pan')
dep.val   # [128, 200, 50]  — one raw DMX value per fixture

op('yourComp').DmxChannel('ColorRGBI').val
# [(1.0, 0.5, 0.0, 1.0), (0.0, 0.0, 1.0, 1.0)]  — normalized RGBI per fixture
```

#### `DmxChannels` (property)
Return a dict of all channel dependencies: `{channelName: tdu.Dependency}`.

```python
channels = op('yourComp').DmxChannels
channels['Tilt'].val   # [90, 45, 180]
```

#### `GetDmxChannelValues(channelName)`
Return a flat list of all DMX values for a channel across all geometry groups and fixture instances. Useful when a channel spans multiple geometry groups or sequential geometries and you want a single ordered list instead of the nested dict/list structure that `DmxChannel().val` returns.

```python
op('yourComp').GetDmxChannelValues('Pan')
# [128, 200, 50]  — one value per fixture, groups concatenated
```

#### `DmxChannelsByType` (property)
Return a dict grouping all channel attribute names by geometry type.

```python
op('yourComp').DmxChannelsByType
# {'point': ['Pan', 'Tilt'], 'primitive': ['Dimmer', 'Color1']}
```

#### `MasterControlledChannelsByType` (property)
Same shape as `DmxChannelsByType` but filtered to only channels whose GDTF `LogicalChannel.master` is `"Grand"`. Use this to know which channels should be scaled by an intensity master or zeroed on blackout.

```python
op('yourComp').MasterControlledChannelsByType
# {'point': [], 'primitive': ['Dimmer', 'BackgroundDimmer']}
```

---

## Development

The Python package lives in `src/TDGdtf` with a standard src layout:

```
src/TDGdtf/
├── core/           # TD-independent: GDTF parsing and data classes
│   ├── parser.py   #   GDTFParser — pygdtf → TouchDesignerFixture
│   ├── fixture.py  #   data classes and serializable channel functions
│   └── utils.py    #   TD parameter name sanitization
├── td/             # TouchDesigner-only (references project, tdu, op)
│   └── FixtureExt.py  # COMP extension: network builder, params, instances
└── tdgdtfFixture.tox  # packaged component
```

Requires Python 3.11+ and [pygdtf](https://pypi.org/project/pygdtf/). The `core` package can be developed and tested outside TouchDesigner:

```bash
pip install -e .[dev]
```

Sample GDTF files for testing are in `gdtfSampleFiles/`.

### Typing

The stored channel-template schema is typed via `TypedDict`s in `core/fixture.py`
(`ChannelTemplate`, `ChannelFunctionDict`, `ChannelSetDict`). The TD-independent core is
checked with mypy (configured in `pyproject.toml`):

```bash
python -m mypy
```

`td/FixtureExt.py` annotates TouchDesigner types (`COMP`, `Par`, `tdu.Dependency`) via
[tdi](https://github.com/touchdesigner/tdi), Derivative's interface library shipped in
`<TouchDesigner>/bin/Lib/tdi`. It is imported under `typing.TYPE_CHECKING` only, so IDEs
and linters resolve TD builtins while nothing extra is imported at runtime.

### Releasing

Releases are built by the tag-triggered GitHub workflow. To publish a new release:

1. Bump `__version__` in `src/TDGdtf/__init__.py` (`pyproject.toml` reads it dynamically) and commit.
2. Tag the commit `v<version>` — the tag must match `__version__` exactly, or the workflow fails.
3. Push the commit and the tag: `git push origin master v<version>`.

The workflow builds the sdist and wheel and creates a GitHub release with notes auto-generated
from the commit messages since the previous tag.

---

## AI Transparency

[Claude](https://claude.com/claude-code) (Anthropic) was used in the development of this
project, primarily for documentation as well as Python optimizations and robustness.

## License

Shared Use License, Derivative Inc. — see [LICENSE](LICENSE).
