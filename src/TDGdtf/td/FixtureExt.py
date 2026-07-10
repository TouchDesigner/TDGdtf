"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""
from __future__ import annotations

from TDStoreTools import StorageManager
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple, TYPE_CHECKING
import time
import logging
from pathlib import Path

if TYPE_CHECKING:
	# tdi is Derivative's interface library for linting/autocompletion contexts
	# (shipped in <TouchDesigner>/bin/Lib). Only imported by type checkers/IDEs;
	# at runtime inside TD the real builtins exist.
	from tdi import COMP, Par
	from tdi.tdClasses.TDUClasses import Dependency

class _CompFilter(logging.Filter):
	"""Stamps records with the owning COMP's path (or 'core' for non-COMP records)."""
	def __init__(self, comp=None):
		super().__init__()
		self.comp = comp
	def filter(self, record):
		if not hasattr(record, 'comp'):
			record.comp = self.comp.path if self.comp is not None else 'core'
		return True

logger = logging.getLogger('TDGdtfFixture_logger')
logger.setLevel(logging.DEBUG)
if not logger.handlers:
	_fh = logging.FileHandler(Path(project.folder) / 'tdgdtf_fixture.log')
	_fh.setLevel(logging.DEBUG)
	_fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s [%(comp)s] - %(message)s'))
	_fh.addFilter(_CompFilter(None))
	logger.addHandler(_fh)
	# route the TD-independent core modules (TDGdtf.core.*) into the same log file
	_coreLogger = logging.getLogger('TDGdtf')
	_coreLogger.setLevel(logging.DEBUG)
	_coreLogger.addHandler(_fh)

from TDGdtf.core.fixture import (
	ChannelFunctionDict,
	ChannelTemplate,
	DMXChannelFunction,
	DMXModeInfo,
	DMXValue,
	TDDMXChannel,
	TouchDesignerFixture,
)
from TDGdtf.core.parser import GDTFParser
from TDGdtf.core.utils import legalTdParName

tag = 'GDTFPARSER'


def _parSuffixes(components: int) -> List[str]:
	"""Per-component TD par name suffixes: size-1 pars use the bare name, size>1 pars are Name1..NameN."""
	return [''] if components <= 1 else [str(i + 1) for i in range(components)]


def _chUniqueKey(ch: Mapping[str, Any]) -> str:
	"""Internal storage key for a channel: geoGroup_tdChannelName, or tdChannelName when no group.

	Args:
		ch: A ChannelTemplate (or partial dict with geoGroup/tdChannelName keys).
	"""
	geoGroup = ch.get('geoGroup')
	base = ch.get('tdChannelName') or ch.get('name', '')
	return '{}_{}'.format(geoGroup, base) if geoGroup else base


class DMXLogicalChannel:
	"""Pure data/logic object representing a single DMX logical channel.
	No TouchDesigner operator references — all parameter UI is handled by FixtureExt.
	"""
	def __init__(self, name: str, channelFunctionDicts: List[ChannelFunctionDict], normalized: bool, bitDepth: int = 8, components: int = 1):
		"""Set up channel functions and default DMX value from stored data.

		Args:
			channelFunctionDicts: List of dicts as produced by _saveState.
			bitDepth: Bit depth of the channel (8, 16, 24, or 32).
		"""
		self.name = name
		self.normalized = normalized
		self.bitDepth = bitDepth
		self.components = components
		channelFunctionList = [DMXChannelFunction.fromDict(d) for d in channelFunctionDicts]
		self.channelFunctions: List[DMXChannelFunction] = channelFunctionList
		self._currentFunction: Optional[DMXChannelFunction] = channelFunctionList[0] if channelFunctionList else None
		self._dmxValue: DMXValue = DMXValue(
			x=self._currentFunction.default.value if self._currentFunction else 0,
			y=0,
			z=0,
			w=0,
		)
		self._currentFunctionValue: float = 0.0
		self._currentChannelSet: int = 0

	def __int__(self) -> int:
		return int(self._dmxValue.x)

	def __str__(self) -> str:
		return f"DMXLogicalChannel(name={self.name}, dmxValue={self._dmxValue})"

	@property
	def dmxValue(self) -> DMXValue:
		return self._dmxValue

	@dmxValue.setter
	def dmxValue(self, value: DMXValue):
		self._dmxValue = value

	@property
	def currentFunction(self) -> int:
		if self._currentFunction and self._currentFunction in self.channelFunctions:
			return self.channelFunctions.index(self._currentFunction)
		return 0

	@currentFunction.setter
	def currentFunction(self, menuIndex: int):
		"""Set the current channel function by its menu index."""
		menuIndex = int(menuIndex)
		if 0 <= menuIndex < len(self.channelFunctions):
			self._currentFunction = self.channelFunctions[menuIndex]
			if self._currentFunction.channelSets:
				self._dmxValue.x = self._currentFunction.channelSets[0].dmxRange[0].value
			self._currentChannelSet = 0
		else:
			logger.warning('Invalid menu index for channel function: %s (max %d)', menuIndex, len(self.channelFunctions) - 1)

	@property
	def currentFunctionValue(self) -> float:
		return self._currentFunctionValue

	@currentFunctionValue.setter
	def currentFunctionValue(self, value: float):
		self._currentFunctionValue = value
		self._dmxValue.x = self.functionValToDmxVal(value)

	@property
	def currentChannelSet(self) -> int:
		return self._currentChannelSet

	@currentChannelSet.setter
	def currentChannelSet(self, value: int):
		value = int(value)
		if self._currentFunction and value < len(self._currentFunction.channelSets):
			channelSet = self._currentFunction.channelSets[value]
			self._dmxValue.x = channelSet.dmxRange[0].value
		self._currentChannelSet = value

	def functionValToDmxVal(self, functionValue: float) -> int:
		"""Convert a physical function value to a DMX value based on the current channel function."""
		if self._currentFunction is None:
			return 0
		physicalFrom, physicalTo = self._currentFunction.physicalRange
		dmxFrom, dmxTo = self._currentFunction.dmxRange
		physMin = physicalFrom.value
		physMax = physicalTo.value
		dmxMin = dmxFrom.value
		dmxMax = dmxTo.value
		if physMax == physMin:
			# zero-width physical range (legal in GDTF) — no mapping possible, use the range start
			return int(dmxMin)
		normalized = tdu.remap(functionValue, physMin, physMax, 0, 1)
		return int(round(tdu.remap(normalized, 0, 1, dmxMin, dmxMax)))

	def toDict(self) -> Dict[str, Any]:
		"""Serialize channel runtime state."""
		return {
			'dmxValue': {'x': self._dmxValue.x, 'y': self._dmxValue.y,
						 'z': self._dmxValue.z, 'w': self._dmxValue.w},
			'currentFunction': self.currentFunction,
			'currentFunctionValue': self._currentFunctionValue,
			'currentChannelSet': self._currentChannelSet,
		}

	def restoreValues(self, d: Dict[str, Any]):
		"""Apply saved runtime state."""
		dmx = d.get('dmxValue', {})
		self._dmxValue = DMXValue(
			dmx.get('x', 0), dmx.get('y', 0),
			dmx.get('z', 0), dmx.get('w', 0),
		)
		funcIdx = d.get('currentFunction', 0)
		if self.channelFunctions and 0 <= funcIdx < len(self.channelFunctions):
			self._currentFunction = self.channelFunctions[funcIdx]
		self._currentFunctionValue = d.get('currentFunctionValue', 0.0)
		self._currentChannelSet = d.get('currentChannelSet', 0)


class FixtureInstance:
	"""One logical fixture instance with its own set of DMX channel values."""
	def __init__(self, fixtureId: int, label: str, channelTemplate: List[ChannelTemplate]):
		"""Create a fixture instance with channels seeded from the template.

		Args:
			channelTemplate: List of channel dicts from _savedChannels.
		"""
		self.fixtureId = fixtureId
		self.label = label
		self.channels: Dict[str, DMXLogicalChannel] = {}
		for ch in channelTemplate:
			self.channels[_chUniqueKey(ch)] = DMXLogicalChannel(
				name=ch['name'],
				channelFunctionDicts=ch['channelFunctions'],
				normalized=ch['normalized'],
				bitDepth=ch['bitDepth'],
				components=ch['components'],
			)

	def setDmxValue(self, channelName: str, value):
		"""Set the raw DMX x-component of a channel.

		Args:
			value: Raw integer DMX value (0 to 2^bitDepth-1).
		"""
		ch = self.channels.get(channelName)
		if ch:
			ch.dmxValue = DMXValue(value, ch.dmxValue.y, ch.dmxValue.z, ch.dmxValue.w)

	def setFunction(self, channelName: str, functionIndex: int):
		"""Switch the active channel function.

		Args:
			functionIndex: 0-based index into the channel's channelFunctions list.
		"""
		ch = self.channels.get(channelName)
		if ch:
			ch.currentFunction = functionIndex

	def setFunctionValue(self, channelName: str, value: float):
		"""Set a physical function value (mapped from physical range to DMX).

		Args:
			value: Physical value within the current function's physical range.
		"""
		ch = self.channels.get(channelName)
		if ch:
			ch.currentFunctionValue = value

	def setChannelSet(self, channelName: str, channelSetIndex: int):
		"""Jump to the start DMX value of a named channel set.

		Args:
			channelSetIndex: 0-based index into the current function's channel sets.
		"""
		ch = self.channels.get(channelName)
		if ch:
			ch.currentChannelSet = channelSetIndex

	def toDict(self) -> Dict[str, Any]:
		"""Serialise all channel runtime state to a plain dict."""
		return {
			'fixtureId': self.fixtureId,
			'label': self.label,
			'channels': {name: ch.toDict() for name, ch in self.channels.items()},
		}

	@classmethod
	def fromDict(cls, d: Dict[str, Any], channelTemplate: List[ChannelTemplate]) -> 'FixtureInstance':
		"""Reconstruct a FixtureInstance from stored state.

		Args:
			d: Dict from toDict.
			channelTemplate: Current channel template for seeding default values.
		"""
		inst = cls(d['fixtureId'], d['label'], channelTemplate)
		for name, chState in d.get('channels', {}).items():
			if name in inst.channels:
				inst.channels[name].restoreValues(chState)
		return inst


class FixtureGroup:
	"""Named group of fixtures referenced by fixture ID."""
	def __init__(self, name: str, fixtureIds: List[int]):
		self.name = name
		self.fixtureIds = list(fixtureIds)

	def toDict(self) -> Dict[str, Any]:
		"""Serialise to a plain dict for storage."""
		return {'name': self.name, 'fixtureIds': self.fixtureIds}

	@classmethod
	def fromDict(cls, d: Dict[str, Any]) -> 'FixtureGroup':
		"""Reconstruct from a plain dict as produced by toDict.

		Args:
			d: Dict from toDict.
		"""
		return cls(d['name'], d['fixtureIds'])

class FixtureExt:
	"""TouchDesigner COMP extension that parses a GDTF file, builds a POP network, and manages DMX fixture instances."""

	def __init__(self, ownerComp: COMP):
		"""Initialise storage, restore persisted state if available."""
		self.ownerComp: COMP = ownerComp
		self.fixture: Optional[TouchDesignerFixture] = None
		self._modes: int = 0

		# logger — per-comp child logger; guard so filters don't pile up across recompiles
		self._log = logging.getLogger(f'TDGdtfFixture_logger.{id(ownerComp)}')
		if not self._log.filters:
			self._log.addFilter(_CompFilter(ownerComp))

		storedItems = [
			{'name': '_fixtureName', 'default': ''},
			{'name': '_fixtureManufacturer', 'default': ''},
			{'name': '_modeMenu', 'default': tdu.MenuObject([], menuLabels=[]), 'dependable': True},
			{'name': '_savedChannels', 'default': []},
			{'name': '_savedModes', 'default': []},
			{'name': '_fixtures', 'default': []},
			{'name': '_groups', 'default': {}},
		]

		self.stored = StorageManager(self, ownerComp, storedItems)

		self._fixtureInstances: List[FixtureInstance] = []
		self._fixtureGroups: Dict[str, FixtureGroup] = {}
		self._channelTemplate: List[ChannelTemplate] = []
		self._channelByName: Dict[str, ChannelTemplate] = {}
		self._chsByAttrName: Dict[str, List[ChannelTemplate]] = {}
		self._parLookup: Dict[str, Tuple[str, str, int]] = {}
		self._dmxDeps: Dict[str, Dependency] = {}
		self._suppressParamCallbacks: bool = False

		if self._savedChannels:
			self._channelTemplate = self._savedChannels
			self._restoreState()

	# ── Properties ──────────────────────────────────────────

	@property
	def Modes(self) -> DMXModeInfo:
		"""Currently active DMXModeInfo."""
		return self.fixture.dmxModes[self._modes]

	@Modes.setter
	def Modes(self, value: Par):
		"""Switch to a different DMX mode, parsing the file first if needed.

		Args:
			value: TD menu parameter value (uses .menuIndex to select the mode).
		"""
		self._modes = value.menuIndex
		mode = self.fixture.dmxModes[self._modes]
		if mode.tdGeometries is None:
			self.Parse()
		else:
			self.CreateNetwork(dmxMode=mode)

	# ── Fixture Management (promoted) ───────────────────────

	def AddFixture(self, label: str = '') -> int:
		"""Create a new fixture instance. Returns its ID (lowest available integer)."""
		fid = self._addFixtureInstance(label)
		self._refreshAfterFixtureChange()
		return fid

	def RemoveFixture(self, fixtureId: int):
		"""Remove a fixture instance by its ID."""
		self._removeFixtureInstance(fixtureId)
		self._refreshAfterFixtureChange()

	def SetFixtureCount(self, count: int):
		"""Add or remove fixtures to reach the desired count. Removes highest IDs first."""
		changed = False
		while len(self._fixtureInstances) < count:
			self._addFixtureInstance()
			changed = True
		while len(self._fixtureInstances) > count:
			highest = max(self._fixtureInstances, key=lambda fi: fi.fixtureId)
			self._removeFixtureInstance(highest.fixtureId)
			changed = True
		if changed:
			self._refreshAfterFixtureChange()

	def _addFixtureInstance(self, label: str = '') -> int:
		"""Append a new FixtureInstance without refreshing menus/storage. Returns its ID."""
		usedIds = {fi.fixtureId for fi in self._fixtureInstances}
		fid = 0
		while fid in usedIds:
			fid += 1
		self._fixtureInstances.append(FixtureInstance(fid, label, self._channelTemplate))
		self._log.debug('AddFixture: id=%d label=%r', fid, label)
		return fid

	def _removeFixtureInstance(self, fixtureId: int):
		"""Remove a FixtureInstance without refreshing menus/storage."""
		before = len(self._fixtureInstances)
		self._fixtureInstances = [fi for fi in self._fixtureInstances if fi.fixtureId != fixtureId]
		if len(self._fixtureInstances) == before:
			self._log.warning('RemoveFixture: fixtureId %d not found', fixtureId)
		else:
			self._log.debug('RemoveFixture: id=%d', fixtureId)

	def _refreshAfterFixtureChange(self):
		"""Refresh menus, storage, and dependencies after fixture instances changed."""
		self._refreshTargetMenu()
		self._persistFixtures()
		self._updateDmxDependencies()

	def GetFixtures(self) -> List[Dict[str, Any]]:
		"""Return list of fixture info dicts: [{fixtureId, label, index}, ...]"""
		return [{'fixtureId': fi.fixtureId, 'label': fi.label, 'index': i}
				for i, fi in enumerate(self._fixtureInstances)]

	def GetFixture(self, identifier: int | str) -> Optional[Dict[str, Any]]:
		"""Return the info dict for a single fixture, or None if not found.

		Args:
			identifier: int fixtureId, or str label (first match).
		"""
		for i, fi in enumerate(self._fixtureInstances):
			if isinstance(identifier, int) and fi.fixtureId == identifier:
				return {'fixtureId': fi.fixtureId, 'label': fi.label, 'index': i}
			if isinstance(identifier, str) and fi.label == identifier:
				return {'fixtureId': fi.fixtureId, 'label': fi.label, 'index': i}
		return None

	def DmxChannel(self, name: str) -> Optional[Dependency]:
		"""Return the tdu.Dependency for a channel. .val is a list of DMX values (one per fixture)."""
		return self._dmxDeps.get(name)

	@property
	def DmxChannels(self) -> Dict[str, Dependency]:
		"""Dict of channel name -> tdu.Dependency. Each .val is a list of DMX values per fixture."""
		return dict(self._dmxDeps)

	@property
	def DmxChannelsByType(self) -> Dict[str, List[str]]:
		"""Dict with 'point' and 'primitive' keys, each a deduplicated list of attribute names."""
		result = {'point': [], 'primitive': []}
		seen = set()
		for ch in self._channelTemplate:
			attrName = ch['name']
			if attrName not in seen:
				seen.add(attrName)
				result[ch.get('geoType', 'primitive')].append(attrName)
		return result

	@property
	def MasterControlledChannelsByType(self) -> Dict[str, List[str]]:
		"""Dict with 'point' and 'primitive' keys listing only Grand-master-controlled channel names."""
		result = {'point': [], 'primitive': []}
		seen = set()
		for ch in self._channelTemplate:
			if not ch.get('masterControlled', False):
				continue
			attrName = ch['name']
			if attrName not in seen:
				seen.add(attrName)
				result[ch.get('geoType', 'primitive')].append(attrName)
		return result

	def GetDmxChannelValues(self, channelName: str) -> List[Any]:
		"""Return a flat list of DMX values for a channel across all groups and fixtures.

		Handles all dep.val shapes:
		  - dict  {geoGroup: [fixtureVals]} — multi-group: groups concatenated in dict order
		  - list  [fixtureVals]             — single-group sequential or primitive
		Each fixtureVal is a scalar (float/int), a list of instance values, or a tuple
		for multi-component channels (RGBA).
		"""
		dep = self._dmxDeps.get(channelName)
		if dep is None:
			return []
		val = dep.val
		groups = val.values() if isinstance(val, dict) else [val]
		result = []
		for groupVals in groups:
			for fiVal in groupVals:
				if isinstance(fiVal, list):
					result.extend(fiVal)
				else:
					result.append(fiVal)
		return result

	# ── Group Management (promoted) ─────────────────────────

	def CreateGroup(self, name: str, fixtureIds: List[int]):
		"""Create or replace a named group of fixture IDs."""
		knownIds = {fi.fixtureId for fi in self._fixtureInstances}
		for fid in fixtureIds:
			if fid not in knownIds:
				self._log.warning('CreateGroup %r: fixtureId %d does not exist', name, fid)
		self._fixtureGroups[name] = FixtureGroup(name, fixtureIds)
		self._refreshTargetMenu()
		self._persistFixtures()

	def DeleteGroup(self, name: str):
		"""Delete a named group."""
		self._fixtureGroups.pop(name, None)
		self._refreshTargetMenu()
		self._persistFixtures()

	def GetGroups(self) -> Dict[str, List[int]]:
		"""Return dict of group names to fixture ID lists."""
		return {name: list(g.fixtureIds) for name, g in self._fixtureGroups.items()}

	# ── Value Setters (promoted) ────────────────────────────

	def SetDmxValue(self, channelName: str, value: int, target: int | str = 'all'):
		"""Set raw DMX value on a channel for the given target(s).
		channelName may be an attribute name (updates all groups) or a uniqueName (one group).
		"""
		unames, attrName = self._resolveChannel(channelName)
		for fi in self._resolveTarget(target):
			for uname in unames:
				fi.setDmxValue(uname, value)
		self._afterValueChange(attrName, roles={'value'})

	def SetNormalizedValue(self, channelName: str, value: float, target: int | str = 'all'):
		"""Set a normalized 0-1 value on a channel for the given target(s).
		Only valid for normalized channels; logs a warning and no-ops for non-normalized ones.
		"""
		unames, attrName = self._resolveChannel(channelName)
		ch = self._channelByName.get(attrName)
		if ch is None:
			return
		if not ch['normalized']:
			self._log.warning('SetNormalizedValue: channel %r is not normalized', channelName)
			return
		rawValue = int(round(float(value) * (2 ** ch['bitDepth'] - 1)))
		for fi in self._resolveTarget(target):
			for uname in unames:
				fi.setDmxValue(uname, rawValue)
		self._afterValueChange(attrName, roles={'value'})

	def SetFunction(self, channelName: str, functionIndex: int, target: int | str = 'all'):
		"""Set the active channel function by index for the given target(s)."""
		unames, attrName = self._resolveChannel(channelName)
		for fi in self._resolveTarget(target):
			for uname in unames:
				fi.setFunction(uname, functionIndex)
		self._afterValueChange(attrName)

	def SetFunctionValue(self, channelName: str, value: float, target: int | str = 'all'):
		"""Set a physical function value for the given target(s)."""
		unames, attrName = self._resolveChannel(channelName)
		for fi in self._resolveTarget(target):
			for uname in unames:
				fi.setFunctionValue(uname, value)
		self._afterValueChange(attrName, roles={'value', 'functionvalue'})

	def SetChannelSet(self, channelName: str, channelSetIndex: int, target: int | str = 'all'):
		"""Set the active channel set by index for the given target(s)."""
		unames, attrName = self._resolveChannel(channelName)
		for fi in self._resolveTarget(target):
			for uname in unames:
				fi.setChannelSet(uname, channelSetIndex)
		self._afterValueChange(attrName, roles={'value', 'channelset'})

	# ── Parsing & Network Creation ──────────────────────────

	def Parse(self):
		"""Parse the GDTF file and build the POP network for the active DMX mode.
		Preserves the currently selected mode by name; falls back to the first mode if no match.
		"""
		t0 = time.time()
		gdtfFile = self.ownerComp.par.Gdtffile.eval()
		self._log.info('Parsing GDTF file: %s', gdtfFile)

		# Read current mode name before _modeMenu is rebuilt
		modesPar = self.ownerComp.par['Modes']
		currentModeName = modesPar.val if modesPar is not None else None

		parser = GDTFParser()
		fixture = parser.parseGdtfFile(gdtfFile)
		self._log.debug('parseGdtfFile: %.3fs', time.time() - t0)
		self.fixture = fixture
		menuNames = [m.name for m in fixture.dmxModes]
		self._modeMenu = tdu.ParMenu(menuNames, menuLabels=menuNames)
		self._fixtureName = fixture.name
		self._fixtureManufacturer = fixture.manufacturer

		if currentModeName in menuNames:
			modeIndex = menuNames.index(currentModeName)
			self._log.debug('Parse: matched existing mode %r at index %d', currentModeName, modeIndex)
		else:
			modeIndex = 0
			self._log.debug('Parse: mode %r not found in new file, defaulting to index 0', currentModeName)
		self._modes = modeIndex

		self._log.debug('CreateNetwork start: %.3fs', time.time() - t0)
		self.CreateNetwork(fixture.dmxModes[modeIndex], myTime=t0)
		self._log.info('Parse complete (%s %s, %d modes): %.3fs', fixture.manufacturer, fixture.name, len(fixture.dmxModes), time.time() - t0)

	def CreateNetwork(self, dmxMode: Optional[DMXModeInfo] = None, myTime: float = 0):
		"""
		Create the TouchDesigner network for the fixture based on the parsed GDTF data.
		"""
		def _createOp(opType, name):
			"""Helper function to create an operator of a given type with a specific name."""
			newOp = self.ownerComp.create(opType, name)
			newOp.tags = [tag]
			return newOp

		if not self.fixture:
			self._log.error('CreateNetwork called with no fixture data')
			raise ValueError("No fixture data available. Please parse a GDTF file first.")

		if dmxMode is None:
			dmxMode = self.fixture.dmxModes[0]

		# delete all nodes associated with this tag
		for operator in self.ownerComp.findChildren(tags=[tag]):
			operator.destroy()
		# clear out the fixtureOp's sequential dmx channels
		fixtureOp = self.ownerComp.op('fixture')
		fixtureOp.seq.dmxchan.numBlocks = 1
		for parGroup in fixtureOp.seq.dmxchan.blocks[0].parGroup:
			parGroup.reset()

		# clear out custom parameters for the Channel Functions page
		channelFunctionsPage = self.ownerComp.customPages['Channel Functions']
		for parGroup in channelFunctionsPage.parGroups:
			parGroup.destroy()

		self._log.debug('CreateNetwork: cleanup old ops/params: %.3fs', time.time() - myTime)
		allChannels = []
		# first get the geometries
		primitives = []
		lineStrips = []
		primitiveMerge = None
		lineStripMerge = None
		geometries = dmxMode.tdGeometries if dmxMode.tdGeometries else []
		for geo in geometries:
			geoName = geo.name.lower()
			geoName = tdu.validName(geoName)
			groupName = None
			if geo.isSequential:
				# add in the parent name so that we can identify it more easily
				geoName = '{}_{}'.format(geo.parent.name.lower(), geoName)
				# this must be a linestrip
				geoType = 'point'
				geoOp = _createOp(linePOP, 'line_{}'.format(geoName))
				geoOp.par.divs = 1
				geoOp.cook(force=True)
				geoOp.seq.pt.numBlocks = len(geo.sequentialMembers)
				for c, p in enumerate(geo.sequentialMembers):
					pos = sum(p.position.matrix, [])
					pos = tdu.Matrix(pos).getTranspose()
					s, r, t = pos.decompose()
					geoOp.seq.pt[c].parGroup.pos = t
				geoOp.seq.attr.numBlocks = len(geo.tdDmxChannels) if geo.tdDmxChannels else 0
				groupOp = _createOp(groupPOP, 'group_{}'.format(geoName))
				groupOp.par.grname = geoName
				groupName = geoName
				# wire the geometry to the group
				geoOp.outputConnectors[0].connect(groupOp.inputConnectors[0])
				attrOp = geoOp
				lineStrips.append(groupOp)
			else:
				# this must be a point primitive
				geoType = 'primitive'
				geoOp = _createOp(pointPOP, 'point_{}'.format(geoName))
				# we need to add a attribute pop to add primitive attributes
				attrOp = _createOp(attributePOP, 'attr_{}'.format(geoName))
				# set the attribute class parameter
				attrOp.par.attrclass = 'primitive'
				attrOp.seq.attr.numBlocks = len(geo.tdDmxChannels) if geo.tdDmxChannels else 0
				# wire up the attribute to the geometry
				geoOp.outputConnectors[0].connect(attrOp.inputConnectors[0])
				primitives.append(attrOp)

			
			attrOp.cook(force=True)

			# add all attributes
			for c, channel in enumerate(geo.tdDmxChannels or []):
				channel.geoGroup = groupName
				channel.geoType = geoType
				channel.instances = len(geo.sequentialMembers) if geo.isSequential else 1
				channel.tdChannelName = tdu.validName(channel.name)
				allChannels.append(channel)
				seqItem = attrOp.seq.attr[c]
				seqItem.par.customname = channel.tdChannelName
				seqItem.par.numcomps = channel.components

		self._log.debug('CreateNetwork: %d geos, %d channels: %.3fs', len(geometries), len(allChannels), time.time() - myTime)
		# first combine the lineStrips
		if len(lineStrips) > 1:
			lineStripMerge = _createOp(mergePOP, 'lineStripMerge')
			for c, stripOp in enumerate(lineStrips):
				# wire the line strips to the merge
				stripOp.outputConnectors[0].connect(lineStripMerge.inputConnectors[c])
			# now convert the multiple linestrips into a single linestrip primitive
			primOp = _createOp(primitivePOP, 'primitive_lineStrip')
			primOp.par.keep = True
			primOp.par.method = 'pattern'
			primOp.par.prim0type = 'linestrip'
			# wire the merge to the primitive
			lineStripMerge.outputConnectors[0].connect(primOp.inputConnectors[0])
			lineStripMerge = primOp

		# next combine the primitives
		if len(primitives) > 1:
			primitiveMerge = _createOp(attributecombinePOP, 'primitiveMerge')
			primitiveMerge.par.attrclass = 'primitive'
			primitiveMerge.seq.input.numBlocks = len(primitives)
			for c, primAttrOp in enumerate(primitives):
				# wire the primitives to the merge
				primAttrOp.outputConnectors[0].connect(primitiveMerge.inputConnectors[c])
				primitiveMerge.seq.input[c].par.attrs = '*'

		# next combine primitives
		attrCombineOp = _createOp(attributecombinePOP, 'attcombine')
		attrCombineOp.par.attrclass = 'primitive'
		if lineStripMerge:
			# wire the line strip merge to the attribute combine
			lineStripMerge.outputConnectors[0].connect(attrCombineOp.inputConnectors[len(attrCombineOp.inputs)])
		elif lineStrips:
			# wire the first line strip directly to the attribute combine
			lineStrips[0].outputConnectors[0].connect(attrCombineOp.inputConnectors[len(attrCombineOp.inputs)])
		attrCombineOp.cook(force=True)
		if primitiveMerge:
			# wire the primitive merge to the attribute combine
			primitiveMerge.outputConnectors[0].connect(attrCombineOp.inputConnectors[len(attrCombineOp.inputs)])
		elif primitives:
			# wire the primitives directly to the attribute combine
			primitives[0].outputConnectors[0].connect(attrCombineOp.inputConnectors[len(attrCombineOp.inputs)])

		attrCombineOp.cook(force=True)
		for i in range(len(attrCombineOp.inputs)):
			attrCombineOp.seq.input[i].par.attrs = '*'

		self._log.debug('CreateNetwork: merge/combine wired: %.3fs', time.time() - myTime)
		# create all dmx channels in fixture
		fixtureOp.seq.dmxchan.numBlocks = max(1, len(allChannels))
		allChannels.sort(key=lambda channel: channel.dmxOffset[0])
		for c, channel in enumerate(allChannels):
			seqItem = fixtureOp.seq.dmxchan[c]
			seqItem.par.valuetype = channel.geoType
			if channel.geoGroup is not None:
				seqItem.par.group = channel.geoGroup
				seqItem.par.name = '{}_{}'.format(channel.geoGroup, channel.tdChannelName)
			else:
				seqItem.par.name = channel.tdChannelName
			seqItem.par.attr = channel.tdChannelName
			seqItem.par.valueres = 'b{}'.format(channel.bitDepth)
			seqItem.par.merge = channel.mergeWithAbove
			seqItem.par.normalized = channel.normalized

		self._log.debug('CreateNetwork: fixture seq dmxchan set: %.3fs', time.time() - myTime)
		# save channel template and build channel params
		t_save = time.time()
		self._saveState(allChannels)
		self._log.debug('CreateNetwork: _saveState: %.3fs', time.time() - t_save)
		self._channelTemplate = self._savedChannels
		t_cp = time.time()
		self._createChannelParams(self._channelTemplate)
		self._log.debug('CreateNetwork: _createChannelParams: %.3fs', time.time() - t_cp)

		# rebuild or create fixture instances against the new template, then refresh display
		t_ref = time.time()
		self._rebuildFixtureInstances()
		self._refreshTargetMenu()
		self._updateDisplayParams()
		self._log.debug('CreateNetwork: rebuild+refresh: %.3fs', time.time() - t_ref)

		# layout created operators
		self.ownerComp.layout(self.ownerComp.findChildren(tags=[tag]))

		# force cook the master tables
		self.ownerComp.op('table_pointMaster').cook(force=True)
		self.ownerComp.op('table_primMaster').cook(force=True)

	# ── Private Helpers ─────────────────────────────────────

	def _afterValueChange(self, attrName: str, roles: Optional[Set[str]] = None):
		"""Refresh dependency, display params, and storage after a channel value change."""
		self._updateDmxDependency(attrName)
		self._updateChannelDisplayParams(attrName, roles=roles)
		self._persistFixtures()

	def _resolveChannel(self, channelName: str) -> Tuple[List[str], str]:
		"""Return (uniqueNames, attrName) for a given attrName or uniqueName.

		If channelName is an attribute name (key in _chsByAttrName), returns all uniqueNames
		for all geometry groups sharing that attribute, plus the attrName itself.
		If channelName is a uniqueName, returns [channelName] and resolves the attrName.
		"""
		if channelName in self._chsByAttrName:
			unames = [_chUniqueKey(ch) for ch in self._chsByAttrName[channelName]]
			return unames, channelName
		# uniqueName passed directly — find attrName by scanning template
		for ch in self._channelTemplate:
			if _chUniqueKey(ch) == channelName:
				return [channelName], ch['name']
		return [channelName], channelName

	def _createChannelParams(self, channelTemplate: List[ChannelTemplate]):
		"""Create Channel Functions page parameters from the channel template (CONSTANT mode, writable)."""
		chFuncPage = self.ownerComp.customPages['Channel Functions']

		# Control Target parameter
		ctPar = chFuncPage.appendStrMenu('Controltarget', label='Control Target')
		ctPar.menuNames = ['all']
		ctPar.menuLabels = ['All']
		ctPar.default = 'all'
		ctPar.val = 'all'
		ctPar.startSection = True

		seen = set()
		for ch in channelTemplate:
			attrName = ch['name']
			if attrName in seen:
				continue
			seen.add(attrName)
			valParName = legalTdParName(attrName)
			cfDicts = ch['channelFunctions']
			firstDict = cfDicts[0] if cfDicts else None

			if ch['normalized']:
				valPar = chFuncPage.appendFloat(valParName, label=ch['name'], size=ch['components'])
				valPar.normMin = 0
				valPar.normMax = 1
				valPar.min = 0
				valPar.max = 1
				for i in range(ch['components']):
					valPar[i].default = tdu.remap(firstDict['default'], 0, 2 ** ch['bitDepth'] - 1, 0, 1) if firstDict else 0
					valPar[i].clampMin = True
					valPar[i].clampMax = True
					valPar[i].startSection = True
					valPar[i].mode = ParMode.CONSTANT
			else:
				valPar = chFuncPage.appendInt(valParName, label=ch['name'])
				valPar.normMin = 0
				valPar.normMax = 2 ** ch['bitDepth'] - 1
				valPar.min = 0
				valPar.max = 2 ** ch['bitDepth'] - 1
				valPar.clampMin = True
				valPar.clampMax = True
				valPar.startSection = True
				valPar.mode = ParMode.CONSTANT

				chFuncMenu = chFuncPage.appendMenu('{}function'.format(valParName), label='Function')
				menuLabels = [d['name'] for d in cfDicts]
				chFuncMenu[0].menuNames = list(range(len(menuLabels)))
				chFuncMenu[0].menuLabels = menuLabels
				chFuncMenu[0].mode = ParMode.CONSTANT

				chFuncVal = chFuncPage.appendFloat('{}value'.format(valParName), label='Function Value')
				chFuncVal.clampMin = True
				chFuncVal.clampMax = True
				chFuncVal.enable = True
				chFuncVal.mode = ParMode.CONSTANT

				chSetMenu = chFuncPage.appendMenu('{}menu'.format(valParName), label='Channel Set')
				if firstDict and firstDict['channelSets']:
					chSetMenu[0].menuNames = list(range(len(firstDict['channelSets'])))
					chSetMenu[0].menuLabels = [cs['name'] for cs in firstDict['channelSets']]
				chSetMenu[0].enable = True
				chSetMenu[0].mode = ParMode.CONSTANT

				if firstDict:
					normMin = min(firstDict['physicalFrom'], firstDict['physicalTo'])
					normMax = max(firstDict['physicalFrom'], firstDict['physicalTo'])
					chFuncVal.normMin = normMin
					chFuncVal.normMax = normMax
					chFuncVal.min = normMin
					chFuncVal.max = normMax

		self._buildChannelIndexes(channelTemplate)
		self._createDmxDependencies(channelTemplate)

	def _buildChannelIndexes(self, channelTemplate: List[ChannelTemplate]):
		"""Build the channel indexes: par-name → (attrName, role, componentIndex) lookup,
		attrName → first channel dict, and attrName → all channel dicts (one per geo group)."""
		self._parLookup = {}
		self._channelByName = {}
		self._chsByAttrName = {}
		seenParNames: Dict[str, str] = {}
		for ch in channelTemplate:
			attrName = ch['name']
			self._channelByName.setdefault(attrName, ch)  # first group wins for display
			self._chsByAttrName.setdefault(attrName, []).append(ch)
			# Only build parLookup entries for the first occurrence per parBaseName
			parBaseName = legalTdParName(attrName)
			existingAttr = seenParNames.get(parBaseName)
			if existingAttr is not None:
				if existingAttr != attrName:
					self._log.warning('Parameter name collision: %r and %r both sanitize to %r; '
									'the parameters control %r only', existingAttr, attrName, parBaseName, existingAttr)
				continue
			seenParNames[parBaseName] = attrName
			if ch['normalized']:
				for i, suffix in enumerate(_parSuffixes(ch['components'])):
					self._parLookup[parBaseName + suffix] = (attrName, 'normalized', i)
			else:
				self._parLookup[parBaseName] = (attrName, 'value', 0)
				self._parLookup[parBaseName + 'function'] = (attrName, 'function', 0)
				self._parLookup[parBaseName + 'value'] = (attrName, 'functionvalue', 0)
				self._parLookup[parBaseName + 'menu'] = (attrName, 'channelset', 0)

	def _rebuildFixtureInstances(self):
		"""Rebuild fi.channels for all existing instances against the current template.
		Preserves values for channels present in both old and new templates.
		If no instances exist, creates the default first fixture.
		"""
		if not self._fixtureInstances:
			self.AddFixture()
			return
		rebuilt = []
		for fi in self._fixtureInstances:
			oldChannels = fi.channels
			newFi = FixtureInstance(fi.fixtureId, fi.label, self._channelTemplate)
			for name, newCh in newFi.channels.items():
				oldCh = oldChannels.get(name)
				if oldCh:
					newCh.restoreValues(oldCh.toDict())
			rebuilt.append(newFi)
		self._fixtureInstances = rebuilt
		self._persistFixtures()
		self._updateDmxDependencies()

	def _createDmxDependencies(self, channelTemplate: List[ChannelTemplate]):
		"""Create one tdu.Dependency per unique attribute name.
		Multi-group channels (same attr in multiple geoGroups) get a dict-valued dep.
		"""
		self._dmxDeps = {}
		for ch in channelTemplate:
			attrName = ch['name']
			if attrName not in self._dmxDeps:
				multiGroup = len(self._chsByAttrName.get(attrName, [])) > 1
				self._dmxDeps[attrName] = tdu.Dependency({} if multiGroup else [])

		self._updateDmxDependencies()

	def _updateDmxDependency(self, channelName: str):
		"""Recompute dep.val for a single attribute name across all geoGroups and fixture instances.

		For multi-group channels dep.val is {geoGroup: [values_per_fixture]}.
		For single-group channels dep.val is [values_per_fixture] (unchanged format).
		"""
		dep = self._dmxDeps.get(channelName)
		if dep is None:
			return
		chList = self._chsByAttrName.get(channelName, [])
		if not chList:
			return
		multiGroup = len(chList) > 1

		def _extractVal(channel, ch):
			normalized = ch['normalized']
			if ch['components'] > 1:
				comps = ['x', 'y', 'z', 'w'][:ch['components']]
				if normalized:
					scale = 2 ** ch['bitDepth'] - 1
					return tuple(float(getattr(channel.dmxValue, c)) / scale for c in comps)
				return tuple(int(getattr(channel.dmxValue, c)) for c in comps)
			if normalized:
				scale = 2 ** ch['bitDepth'] - 1
				return float(channel.dmxValue.x) / scale
			return int(channel.dmxValue.x)

		if multiGroup:
			result = {}
			for ch in chList:
				uname = _chUniqueKey(ch)
				instances = ch.get('instances', 1)
				groupValues = []
				for fi in self._fixtureInstances:
					channel = fi.channels.get(uname)
					if channel is None:
						continue
					val = _extractVal(channel, ch)
					groupValues.append([val] * instances if instances > 1 else val)
				result[ch.get('geoGroup')] = groupValues
			dep.val = result
		else:
			ch = chList[0]
			uname = _chUniqueKey(ch)
			instances = ch.get('instances', 1)
			values = []
			for fi in self._fixtureInstances:
				channel = fi.channels.get(uname)
				if channel is None:
					continue
				val = _extractVal(channel, ch)
				values.append([val] * instances if instances > 1 else val)
			dep.val = values

	def _updateDmxDependencies(self):
		"""Recompute dep.val for every unique attribute name."""
		for attrName in self._dmxDeps:
			self._updateDmxDependency(attrName)

	def _resolveTarget(self, target: int | str = 'all') -> List[FixtureInstance]:
		"""Parse a target specifier into a deduplicated list of FixtureInstances.
		target can be: int (fixtureId), 'all', group name, or comma-separated mix.
		"""
		if isinstance(target, int):
			target = str(target)
		tokens = [t.strip() for t in str(target).split(',')]
		seen = set()
		result = []
		for token in tokens:
			if token == 'all':
				for fi in self._fixtureInstances:
					if fi.fixtureId not in seen:
						seen.add(fi.fixtureId)
						result.append(fi)
			elif token.isdigit():
				fid = int(token)
				for fi in self._fixtureInstances:
					if fi.fixtureId == fid and fid not in seen:
						seen.add(fid)
						result.append(fi)
						break
			elif token in self._fixtureGroups:
				for fid in self._fixtureGroups[token].fixtureIds:
					for fi in self._fixtureInstances:
						if fi.fixtureId == fid and fid not in seen:
							seen.add(fid)
							result.append(fi)
							break
			else:
				self._log.warning('_resolveTarget: unknown token %r', token)
		return result

	def _refreshTargetMenu(self):
		"""Rebuild the Control Target menu entries from current fixtures and groups."""
		par = self.ownerComp.par['Controltarget']
		if par is None:
			return
		names = ['all'] + [str(fi.fixtureId) for fi in self._fixtureInstances] + list(self._fixtureGroups.keys())
		labels = ['All'] + [
			'{} ({})'.format(fi.fixtureId, fi.label) if fi.label else str(fi.fixtureId)
			for fi in self._fixtureInstances
		] + list(self._fixtureGroups.keys())
		par.menuNames = names
		par.menuLabels = labels

	def _updateDisplayParams(self):
		"""Write all channel values to the custom params (full refresh)."""
		myTime = time.time()
		seen = set()
		for ch in self._channelTemplate:
			attrName = ch['name']
			if attrName not in seen:
				seen.add(attrName)
				self._updateChannelDisplayParams(attrName)
		self._log.debug('_updateDisplayParams: %.3fs', time.time() - myTime)

	def _updateChannelDisplayParams(self, channelName: str, roles: Optional[Set[str]] = None):
		"""Update display params for a single channel. If roles is None, update everything."""
		ch = self._channelByName.get(channelName)
		if ch is None:
			return

		ctPar = self.ownerComp.par['Controltarget']
		targetStr = str(ctPar.eval()) if ctPar is not None else 'all'
		fixtures = self._resolveTarget(targetStr)
		if not fixtures:
			return
		fi = fixtures[0]
		# fi.channels is keyed by uniqueName; look up the first group's uniqueName for this attr
		uname = _chUniqueKey(ch)
		channel = fi.channels.get(uname)
		if channel is None:
			return

		parBaseName = legalTdParName(channelName)
		self._suppressParamCallbacks = True
		try:
			if ch['normalized']:
				if roles is None or 'normalized' in roles or 'value' in roles:
					compNames = ['x', 'y', 'z', 'w'][:ch['components']]
					suffixes = _parSuffixes(ch['components'])
					scale = 2 ** ch['bitDepth'] - 1
					for i, comp in enumerate(compNames):
						par = self.ownerComp.par[parBaseName + suffixes[i]]
						if par is not None:
							par.val = getattr(channel.dmxValue, comp) / scale
			else:
				if roles is None or 'value' in roles:
					par = self.ownerComp.par[parBaseName]
					if par is not None:
						par.val = channel.dmxValue.x

				if roles is None or 'function' in roles:
					funcPar = self.ownerComp.par[parBaseName + 'function']
					if funcPar is not None:
						funcPar.val = channel.currentFunction

				if roles is None or 'functionvalue' in roles:
					valPar = self.ownerComp.par[parBaseName + 'value']
					if valPar is not None:
						if roles is None or 'function' in roles:
							if channel._currentFunction:
								physicalRange = channel._currentFunction.physicalRange
								normMin = min(physicalRange[0].value, physicalRange[1].value)
								normMax = max(physicalRange[0].value, physicalRange[1].value)
								valPar.normMin = normMin
								valPar.normMax = normMax
								valPar.min = normMin
								valPar.max = normMax
						valPar.val = channel.currentFunctionValue

				if roles is None or 'channelset' in roles:
					menuPar = self.ownerComp.par[parBaseName + 'menu']
					if menuPar is not None:
						if roles is None or 'function' in roles:
							if channel._currentFunction and channel._currentFunction.channelSets:
								menuPar.menuNames = list(range(len(channel._currentFunction.channelSets)))
								menuPar.menuLabels = [cs.name for cs in channel._currentFunction.channelSets]
						menuPar.val = channel.currentChannelSet
		finally:
			self._suppressParamCallbacks = False

	def _onTargetChanged(self):
		"""Called when the Controltarget parameter changes."""
		self._updateDisplayParams()

	def _onChannelParChange(self, par: Par):
		"""Called by parexec when a channel parameter is changed by the user."""
		if self._suppressParamCallbacks:
			return

		lookup = self._parLookup.get(par.name)
		if lookup is None:
			return

		channelName, role, compIdx = lookup
		ctPar = self.ownerComp.par['Controltarget']
		targetStr = str(ctPar.eval()) if ctPar is not None else 'all'

		if role == 'normalized':
			compName = ['x', 'y', 'z', 'w'][compIdx]
			unames, attrName = self._resolveChannel(channelName)
			for fi in self._resolveTarget(targetStr):
				for uname in unames:
					channel = fi.channels.get(uname)
					if channel:
						setattr(channel.dmxValue, compName, par.eval() * (2 ** channel.bitDepth - 1))
			self._afterValueChange(attrName, roles={'normalized'})
		elif role == 'value':
			self.SetDmxValue(channelName, par.eval(), targetStr)
		elif role == 'function':
			self.SetFunction(channelName, int(par.eval()), targetStr)
		elif role == 'functionvalue':
			self.SetFunctionValue(channelName, par.eval(), targetStr)
		elif role == 'channelset':
			self.SetChannelSet(channelName, int(par.eval()), targetStr)

	def _persistFixtures(self):
		"""Write current fixture and group state to storage."""
		self._fixtures = [fi.toDict() for fi in self._fixtureInstances]
		self._groups = {n: g.toDict() for n, g in self._fixtureGroups.items()}

	def _saveState(self, allChannels: List[TDDMXChannel]):
		"""Serialize channel template data to storage so it survives a TD restart."""
		channelData: List[ChannelTemplate] = []
		for channel in allChannels:
			channelFunctions = []
			logicalChannels = getattr(channel.channelObj, 'logical_channels', None) if channel.channelObj else None
			if logicalChannels:
				channelFunctions = [DMXChannelFunction(cf).toDict() for cf in logicalChannels[0].channel_functions]
			channelData.append({
				'name': channel.name,
				'tdChannelName': channel.tdChannelName,
				'geoGroup': channel.geoGroup,
				'uniqueName': _chUniqueKey({
					'geoGroup': channel.geoGroup,
					'tdChannelName': channel.tdChannelName,
				}),
				'normalized': channel.normalized,
				'bitDepth': channel.bitDepth,
				'components': channel.components,
				'geoType': channel.geoType,
				'instances': channel.instances,
				'masterControlled': channel.masterControlled,
				'channelFunctions': channelFunctions,
			})
		self._savedChannels = channelData
		self._savedModes = [{'name': m.name, 'description': m.description} for m in self.fixture.dmxModes]
		self._persistFixtures()

	def _restoreState(self):
		"""Reconstruct Python-side objects from stored data without reading the GDTF file."""
		# Migrate old stored templates that predate geoGroup/uniqueName/bitDepth fields
		for ch in self._channelTemplate:
			if 'geoGroup' not in ch:
				ch['geoGroup'] = None
			if 'uniqueName' not in ch:
				ch['uniqueName'] = _chUniqueKey(ch)
			if 'masterControlled' not in ch:
				ch['masterControlled'] = False
			if 'bitDepth' not in ch:
				ch['bitDepth'] = ch.pop('byteCount', 8)

		# Rebuild a lightweight fixture stub so Modes property works
		self.fixture = TouchDesignerFixture(
			name=self._fixtureName,
			manufacturer=self._fixtureManufacturer,
			dmxModes=[DMXModeInfo(name=m['name'], description=m['description']) for m in self._savedModes],
		)

		# Reconstruct fixture instances from storage
		self._fixtureInstances = [
			FixtureInstance.fromDict(d, self._channelTemplate)
			for d in self._fixtures
		]

		# Reconstruct groups from storage
		for name, gData in self._groups.items():
			self._fixtureGroups[name] = FixtureGroup.fromDict(gData)

		# Recreate channel params and refresh display
		self._createChannelParams(self._channelTemplate)
		self._refreshTargetMenu()
		self._updateDisplayParams()
		self._log.info('State restored: %d channels, %d fixtures, %d groups',
					len(self._savedChannels), len(self._fixtureInstances), len(self._fixtureGroups))