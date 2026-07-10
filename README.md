# TDGdtf

A TouchDesigner tool that parses [GDTF](https://gdtf-share.com) fixture files and builds component networks with POP geometry, DMX channel attributes, and a full parameter UI.

## Setup

### Installation

Install the package into a Python virtual environment used by TouchDesigner (e.g. one
managed by TD's Python Environment Manager):

```bash
pip install TDGdtf
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

All parsed data — the channel template, fixture instances, groups, and every channel value — is persisted via TouchDesigner's StorageManager. Values are saved on every change, so the component fully restores its state after a project restart without re-reading the GDTF file.

### Parsing behavior

- The currently selected DMX mode is preserved by name when re-parsing; if the new file has no mode with that name, the first mode is used.
- Consecutive channels sharing a GDTF ActivationGroup (e.g. `ColorAdd_R/G/B`) are merged into one multi-component vector channel — but only when all channels have the same bit depth and exactly one channel function each. Incompatible channels (e.g. a 16-bit `Gobo1Pos` next to an 8-bit `Gobo1PosRotate`) stay separate, since a DMX channel block cannot mix bit depths and a vector component cannot expose its own function menu.
- GDTF *virtual* channels (channels without a DMX offset) have no DMX footprint and are skipped with a warning.
- Channels whose attribute is missing from the fixture's attribute list are kept but logged as a warning, and are never merged with neighbouring channels.
- Channel names are sanitized into TD parameter names; if two different attributes sanitize to the same parameter name, a warning is logged and only the first one gets parameters.

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

### Methods

| Method | Description |
|---|---|
| `DmxChannel(name)` | Return the `tdu.Dependency` for a single channel by name, or `None` if not found. |
| `GetDmxChannelValues(name)` | Return a flat list of DMX values for a channel across all groups and fixtures. |

### Properties

| Property | Type | Description |
|---|---|---|
| `Modes` | get/set | Get the current `DMXModeInfo` object. Assign a TD menu parameter value (with `.menuIndex`) to switch modes and rebuild the network. |
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

---

## License

Shared Use License, Derivative Inc. — see [LICENSE](LICENSE).
