# TouchDesigner Python Project

## Project Context
This is a TouchDesigner project. All Python code runs inside TouchDesigner's embedded Python 3.x
interpreter. Do not suggest standard desktop Python patterns (e.g. `import os` for file paths,
`__main__` guards) unless explicitly asked. Prefer TD-native APIs at all times.

The project in question here is a redevelopment of TDGDTF: A tool to create a component based on a GDTF fixture file.
The tool will create all bencessary POP geomerty, assign attribues as required and fill in the DMX Fixture POP. Additionally 
all Fixture features will be exposed as custom parameters on the component itself.

It will be important that the component can save the fixture state so that it does not have to reevaluate the gdtf file on resetart.

---

## Operator References

### Accessing Operators
```python
op('opName')                  # by name (relative to current COMP)
op('/project1/base1/opName')  # absolute path
parent()                      # parent COMP
parent(2)                     # two levels up
parent.op('opName')           # using parent shortcut
me                            # the operator running this script
```

### Parameters
```python
op('geo1').par.tx             # read parameter
op('geo1').par.tx = 2.5       # set parameter
op('geo1').par.
op('geo1').par.tx.val         # .val for the constant mode value
op('geo1').par.tx.eval()      # Evaluate a parameter. This value may be derived by the parameter's constant value, expression, export, or bind, dependent on its mode.
op('geo1').par.tx.expr        # read/write expression string
op('geo1').par.tx.mode = ParMode.EXPRESSION
```

---

## Naming Conventions

### Operators
- Use **camelCase** for operator names: `audioAnalyzer`, `particleSystem`
- Prefix by type when clarity helps: `base_controls`, `null_output`, `geo_avatar`
- Avoid default TD names like `base1`, `geo2` — always rename meaningfully

### Parameters & Variables
- Python variables: `camelCase`
- Constants: `ALLCAPS`
- Avoid single-letter variables except loop counters (`i`, `j`)

### Scripts & DATs
- Name script DATs after their purpose: `script_onPulse`, `script_frameStart`
- Callbacks stay in their default callback DAT (e.g. `chopexec1` → rename to `chopexec_audioLevel`)

### Storage (op.store)
- Use namespaced string keys: `'config/bpm'`, `'state/isPlaying'`

---

## TD Python Patterns

### Execute on Frame Start
Use `scriptDAT` with Execute DAT, or the project's `perform` callbacks.
Avoid blocking operations inside `onFrameStart` — keep it fast.

### Storing State
```python
# Preferred: use op storage
parent().store('myKey', value)
parent().fetch('myKey', default)

# Avoid: global Python variables (lost on recompile)
```

### Logging
```python
print('debug info')           # shows in Textport
debug('value:', someVar)      # TD's built-in debug (toggleable)
```

### Extensions
When writing a COMP Extension class:
```python
class MyExtension:
    def __init__(self, ownerComp):
        self.ownerComp = ownerComp

    def MyMethod(self):
        # access ops relative to ownerComp
        op = self.ownerComp.op('null1')
```
- Promote key methods with `Promote to Operator` so they appear as `op('base1').MyMethod()`
- Keep `__init__` lightweight — no heavy computation at init time
- Always use camelcase for variables and functions
- promoted functions start with a capital, non promoted with a small case
---

## Key Libraries Available in TD

### Built-in (no import needed)
- `td` module: implicit — `op()`, `me`, `absTime`, `project`, `ui`, `app`
- `numpy` — available by default in most TD builds
- `TDFunctions` — utility module, import with `import TDFunctions as TDF`

### Common Imports
```python
import numpy as np
import json
import re
import math
```

### OSC / Serial / Web
Use the built-in `oscin`, `oscout`, `serialDAT`, `webClientDAT` OPs rather than Python
socket libraries where possible.

---

## Help & Reference Pages

<!-- Replace these placeholder URLs with your actual bookmarks -->
- **TouchDesigner Documentation** https://docs.derivative.ca
- **TouchDesigner Forum** https://forum.derivative.ca
- **TDILib:** file:///C:/Program Files/Derivative/TouchDesigner.2025.33025/bin/Lib/tdi
- **Offline Help:** file:///C:/Program Files/Derivative/TouchDesigner.2025.33025/Samples/Learn/OfflineHelp/https.docs.derivative.ca
- **GDTF Documentation:** https://www.gdtf.eu/gdtf

---

## What NOT to Do
- Do not use `time.sleep()` — it blocks the cook thread; use timeline or CHOP-based timing
- Do not hardcode absolute file paths; use `app.samplesFolder`, `project.folder`, or `TDFunctions`
- Do not modify UI from a non-main thread
- Do not suggest `if __name__ == '__main__'` — irrelevant in TD scripts
- Do not create new operators via Python unless explicitly asked (prefer network-level setup)