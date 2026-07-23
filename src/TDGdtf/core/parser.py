"""GDTF file parser that converts a fixture definition into TouchDesigner-ready data structures."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygdtf

from .fixture import (
    BitDepth,
    GeoData,
    TDDMXChannel,
    TDGeometry,
    DMXModeInfo,
    TouchDesignerFixture,
)
from .utils import SEQNUMPATTERN, SEQNAMEPATTERN, legalPopName

logger = logging.getLogger(__name__)


class GDTFParser:
    """Parses a GDTF file into a TouchDesignerFixture with geometry and DMX channel data."""

    def __init__(self):
        self._fixture: Optional[pygdtf.FixtureType] = None
        self._attrByName: Dict[str, pygdtf.Attribute] = {}

    def parseGdtfFile(self, gdtfPath: str) -> TouchDesignerFixture:
        """Parse a GDTF file and return a TouchDesignerFixture object"""
        t0 = time.time()
        try:
            fixture = pygdtf.FixtureType(gdtfPath)
        except Exception as exc:
            raise ValueError(f"Could not parse GDTF file: {gdtfPath}") from exc
        logger.debug('pygdtf.FixtureType(): %.3fs', time.time() - t0)
        self._fixture = fixture
        self._attrByName = {a.name: a for a in fixture.attributes}

        name = fixture.name or Path(gdtfPath).stem or "Unnamed Fixture"
        manufacturer = fixture.manufacturer or "Unknown Manufacturer"

        t1 = time.time()
        modes = self._parseDMXModes(fixture)
        logger.debug('_parseDMXModes(): %.3fs', time.time() - t1)

        return TouchDesignerFixture(
            name=name,
            manufacturer=manufacturer,
            dmxModes=modes
        )

    def _parseDMXModes(self, gdtf: pygdtf.FixtureType) -> List[DMXModeInfo]:
        """Build a DMXModeInfo stub for every mode in the fixture.

        Args:
            gdtf: Parsed pygdtf FixtureType to iterate modes from.
        """
        modes = []
        for i in gdtf.dmx_modes:
            t = time.time()
            allChannels = i.dmx_channels
            tdGeoDef = self._getTdGeoDef(allChannels)
            modes.append(DMXModeInfo(
                name=i.name,
                description=i.description,
                tdGeometries=tdGeoDef
            ))
            logger.debug('mode %r (%d ch): %.3fs', i.name, len(allChannels), time.time() - t)
        return modes

    def _getTdGeoDef(self, channels: List[pygdtf.DmxChannel]) -> Optional[List[TDGeometry]]:
        """Loop through all channels and group them based on sequential geometries they belong to.
        In the Fixture POP we use primitive attributes for DMX Channels that affect the whole fixture,
        e.g. channels that are part of the body or base geometry.
        """
        if not channels:
            return None
        assert self._fixture is not None, 'parseGdtfFile must run before _getTdGeoDef'

        geos: Dict[str, GeoData] = {}

        for c in channels:
            geo = self._fixture.geometries.get_geometry_by_name(c.geometry)
            if geo is None:
                logger.warning('Channel %r references unknown geometry %r; channel skipped', c.name, c.geometry)
                continue
            geoParent = self._fixture.geometries.get_geometry_by_name(geo.parent_name)
            if geo.name not in geos:
                geos[geo.name] = GeoData(
                    geo=geo,
                    geoParent=geoParent,
                    channels=[c]
                )
            else:
                geos[geo.name]['channels'].append(c)

        groupedByBaseName: Dict[Tuple[str, Optional[str]], List[Tuple[str, GeoData]]] = {}
        for geoName, geoData in geos.items():
            basename = SEQNUMPATTERN.sub('', geoName)
            parentName = geoData['geoParent'].name if geoData['geoParent'] else None

            key = (basename, parentName)
            if key not in groupedByBaseName:
                groupedByBaseName[key] = []
            groupedByBaseName[key].append((geoName, geoData))

        allGeometries = []
        for (baseName, parentName), geoList in groupedByBaseName.items():
            if len(geoList) == 1:
                geoName, geoData = geoList[0]
                allChannels = self._optimizeChannels(geoData['channels'], sequential=False)
                tdGeometry = TDGeometry(
                    name=geoData['geo'].name,
                    geoObj=geoData['geo'],
                    parent=geoData['geoParent'],
                    tdDmxChannels=allChannels,
                    isSequential=False,
                    sequentialMembers=None
                )
            else:
                sequentialMembers = [geoData['geo'] for geoName, geoData in geoList]

                allChannels = self._optimizeChannels(geoList[0][1]['channels'], sequential=True)

                tdGeometry = TDGeometry(
                    name=baseName,
                    geoObj=geoList[0][1]['geo'],
                    parent=geoList[0][1]['geoParent'],
                    tdDmxChannels=allChannels,
                    isSequential=True,
                    sequentialMembers=sequentialMembers
                )
            allGeometries.append(tdGeometry)

        return allGeometries if allGeometries else None

    def _optimizeChannels(self, channels: List[pygdtf.DmxChannel], sequential: bool) -> List[TDDMXChannel]:
        """Optimize the list of channels by merging them based on their activation group.

        Consecutive channels sharing an activation group are merged into one
        multi-component channel only when they are homogeneous: same bit depth and
        exactly one channel function each (see _mergeIncompatibilityReason). The DMX
        Fixture POP cannot mix bit depths within one channel block, and a merged
        component cannot expose per-component channel functions.
        """
        lastActivationGroup = None
        mergeChannelList: List[pygdtf.DmxChannel] = []
        returnList: List[TDDMXChannel] = []

        def _flushMergeList():
            if not mergeChannelList:
                return
            tdChannel = self._createTDDMXChannel(mergeChannelList, sequential, len(returnList) > 0 and sequential)
            if tdChannel is not None:
                returnList.append(tdChannel)

        for c in channels:
            attribute = self._getAttributeByName(c.attribute.str_link)
            if attribute is None:
                logger.warning('Channel %r: attribute %r not found in fixture attribute list; treated as unmergeable',
                               c.name, c.attribute.str_link)
                activationGroup = None
            else:
                activationGroup = attribute.activation_group.str_link
            startNewGroup = not activationGroup or activationGroup != lastActivationGroup
            if not startNewGroup and mergeChannelList:
                reason = self._mergeIncompatibilityReason(c, mergeChannelList[0])
                if reason is not None:
                    logger.info('Not merging channel %r into %r despite shared activation group %r: %s',
                                c.name, mergeChannelList[0].name, activationGroup, reason)
                    startNewGroup = True
            if startNewGroup:
                _flushMergeList()
                mergeChannelList = [c]
            else:
                mergeChannelList.append(c)
            lastActivationGroup = activationGroup
        _flushMergeList()
        return returnList

    @staticmethod
    def _channelFunctionCount(channel: pygdtf.DmxChannel) -> int:
        """Number of channel functions on the channel's first logical channel."""
        if not channel.logical_channels:
            return 0
        return len(channel.logical_channels[0].channel_functions)

    @staticmethod
    def _mergeIncompatibilityReason(candidate: pygdtf.DmxChannel, first: pygdtf.DmxChannel) -> Optional[str]:
        """Why candidate cannot join a vector merge started by first; None when compatible."""
        if candidate.offset is None or first.offset is None:
            return 'virtual channel (no DMX offset)'
        if len(candidate.offset) != len(first.offset):
            return 'bit depth {} vs {}'.format(len(candidate.offset) * 8, len(first.offset) * 8)
        if GDTFParser._channelFunctionCount(candidate) != 1 or GDTFParser._channelFunctionCount(first) != 1:
            return 'channels with multiple channel functions cannot be vector components'
        return None

    def _createTDDMXChannel(self, channelList: List[pygdtf.DmxChannel], sequential: bool, mergeWithAbove: bool) -> Optional[TDDMXChannel]:
        """Create a TDDMXChannel from a list of pygdtf.DmxChannel"""
        if not channelList:
            return None
        firstChannel = channelList[0]
        channelName = firstChannel.name
        if firstChannel.offset is None:
            # virtual channel (Offset="None" in GDTF) — has no DMX footprint to patch
            logger.warning('Skipping virtual channel %r (no DMX offset)', channelName)
            return None
        if not firstChannel.logical_channels:
            logger.warning('Skipping channel %r: no logical channels defined', channelName)
            return None
        if sequential:
            # remove the sequential number portion from the name (e.g. Beam_12_Color_Add_R → Beam_Color_Add_R)
            match = SEQNAMEPATTERN.search(channelName)
            if match:
                channelName = channelName[:match.start()] + channelName[match.end():]

        # sanitize once at the source so POP attribute names, dependency keys, and
        # parameter names all share the same TD-legal channel name
        sanitized = legalPopName(channelName)
        if sanitized != channelName:
            logger.info('Channel %r renamed to %r for TouchDesigner compatibility', channelName, sanitized)
            channelName = sanitized

        logicalChannel = firstChannel.logical_channels[0]
        channelFunctions = logicalChannel.channel_functions
        # if there is more than 1 channel function, this channel is not normalized
        normalized = len(channelFunctions) == 1

        master = getattr(logicalChannel, 'master', None)
        masterControlled = str(master).lower() == 'grand'

        channel = TDDMXChannel(
            name=channelName,
            channelObj=firstChannel,
            dmxBreak=firstChannel.dmx_break,  # TODO: IMPORTANT FOR GEOMETRY MERGING — different breaks = different primitives
            dmxOffset=firstChannel.offset,
            bitDepth=[BitDepth.BIT_8, BitDepth.BIT_16, BitDepth.BIT_24, BitDepth.BIT_32][len(firstChannel.offset) - 1],
            components=len(channelList),
            mergeWithAbove=mergeWithAbove,
            normalized=normalized,
            channelFunctions=channelFunctions,
            masterControlled=masterControlled,
        )
        return channel

    def _getAttributeByName(self, name: str) -> Optional[pygdtf.Attribute]:
        """Look up a GDTF attribute by name from the pre-built index.

        Args:
            name: The GDTF attribute name string (e.g. 'Dimmer', 'ColorAdd_R').
        """
        return self._attrByName.get(name)
