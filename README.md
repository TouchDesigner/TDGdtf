# TDGdtf

A TouchDesigner tool that parses GDTF fixture files and builds component networks with POP geometry, DMX channel attributes, and a full parameter UI.

## Setup

1. Set the **Gdtffile** parameter on the component to point at a `.gdtf` file.
2. Call `Parse()` to read the file, build the operator network, and create channel parameters.
3. Use the **Modes** property or the mode menu parameter to switch DMX modes.

---

## Promoted API Reference

All promoted functions are accessed via `op('yourComp').FunctionName(...)`.

### Parsing & Network

| Method | Description |
|---|---|
| `Parse()` | Parse the GDTF file set in the **Gdtffile** parameter and build the operator network. Preserves the currently selected mode by name; falls back to the first mode if no match exists in the new file. |
| `CreateNetwork(dmxMode=None)` | Rebuild the operator network for a specific DMX mode. Called automatically by `Parse()` and the `Modes` setter. |

### Properties

| Property | Type | Description |
|---|---|---|
| `Modes` | get/set | Get the current DMX mode object. Set with a menu value to switch modes and rebuild the network. |
| `DmxChannels` | dict (read-only) | Dict of `{channelName: tdu.Dependency}`. Each dependency's `.val` is a list of DMX values, one entry per fixture instance. Updates automatically when values change. |
| `DmxChannelsByType` | dict (read-only) | Dict with `'point'` and `'primitive'` keys, each a deduplicated list of attribute names by geometry type. |
| `MasterControlledChannelsByType` | dict (read-only) | Same shape as `DmxChannelsByType` but only includes channels where `LogicalChannel.master == "Grand"` in the GDTF definition. |

---

### Fixture Management

#### `AddFixture(label='')`
Create a new fixture instance. Returns the auto-incremented fixture ID (`int`).

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
Add or remove fixture instances to reach the desired total count. When removing, the highest IDs are removed first.

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
Set a physical function value (in the function's physical units). The value is automatically converted to the corresponding DMX value based on the current channel function's physical-to-DMX mapping.

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
Return the `tdu.Dependency` object for a single channel. The dependency's `.val` holds a list of DMX values, one per fixture instance (ordered by fixture index).

```python
dep = op('yourComp').DmxChannel('Pan')
dep.val   # [128, 200, 50]
```

Because these are `tdu.Dependency` objects, any operator expression referencing `.val` will automatically re-cook when the values change.

#### `DmxChannels` (property)
Return a dict of all channel dependencies: `{channelName: tdu.Dependency}`.

```python
channels = op('yourComp').DmxChannels
channels['Tilt'].val   # [90, 45, 180]
```

For multi-component channels (e.g. normalized RGBI), each entry in the list is a tuple:

```python
op('yourComp').DmxChannel('ColorRGBI').val
# [(1.0, 0.5, 0.0, 1.0), (0.0, 0.0, 1.0, 1.0)]
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

#### `GetDmxChannelValues(channelName)`
Return a flat list of all DMX values for a channel across all geometry groups and fixture instances. Useful when a channel spans multiple geometry groups (e.g. a sequential fixture) and you want a single ordered list instead of the nested dict/list structure that `DmxChannel().val` returns.

```python
op('yourComp').GetDmxChannelValues('Pan')
# [128, 200, 50]  — one value per fixture, groups concatenated
```

---

## License

See [LICENSE](LICENSE).