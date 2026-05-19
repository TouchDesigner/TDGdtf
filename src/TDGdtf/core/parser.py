"""GDTF file parser that converts a fixture definition into TouchDesigner-ready data structures."""
import pygdtf
import time
from pathlib import Path
from typing import List, Optional

from .fixture import (
    BitDepth,
    GeoData,
    TDDMXChannel,
    TDGeometry,
    DMXModeInfo,
    TouchDesignerFixture,
)
from .utils import SEQNUMPATTERN, SEQNAMEPATTERN


class GDTFParser:
    """Parses a GDTF file into a TouchDesignerFixture with geometry and DMX channel data."""

    def __init__(self):
        self._fixture: Optional[pygdtf.FixtureType] = None

    def parseGdtfFile(self, gdtfPath: str) -> TouchDesignerFixture:
        """Parse a GDTF file and return a TouchDesignerFixture object"""
        t0 = time.time()
        fixture = pygdtf.FixtureType(gdtfPath)
        print(f'[GDTF TIMER] pygdtf.FixtureType():        {time.time()-t0:.3f}s')
        self._fixture = fixture
        self._attrByName = {a.name: a for a in fixture.attributes}

        if self._fixture is None:
            raise ValueError(f"Could not parse GDTF file: {gdtfPath}")

        name = fixture.name or Path(gdtfPath).stem or "Unnamed Fixture"
        manufacturer = fixture.manufacturer or "Unknown Manufacturer"

        t1 = time.time()
        modes = self._parseDMXModes(fixture)
        print(f'[GDTF TIMER] _parseDMXModes():             {time.time()-t1:.3f}s')

        return TouchDesignerFixture(
            name=name,
            manufacturer=manufacturer,
            attributes=[],
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
            print(f'[GDTF TIMER]   mode "{i.name}" ({len(allChannels)} ch): {time.time()-t:.3f}s')
        return modes

    def _getTdGeoDef(self, channels: List[pygdtf.DmxChannel]) -> Optional[List[TDGeometry]]:
        """Loop through all channels and group them based on sequential geometries they belong to.
        In the Fixture POP we use primitive attributes for DMX Channels that affect the whole fixture,
        e.g. channels that are part of the body or base geometry.
        """
        if not channels:
            return None

        geos = {}

        for c in channels:
            geo = self._fixture.geometries.get_geometry_by_name(c.geometry)
            geoParent = self._fixture.geometries.get_geometry_by_name(geo.parent_name)
            if geo.name not in geos:
                geos[geo.name] = GeoData(
                    geo=geo,
                    geoParent=geoParent,
                    channels=[c]
                )
            else:
                geos[geo.name]['channels'].append(c)

        groupedByBaseName = {}
        for geoName, geoData in geos.items():
            basename = SEQNUMPATTERN.sub('', geoName)
            parentId = id(geoData['geoParent'] if geoData['geoParent'] else None)

            key = (basename, parentId)
            if key not in groupedByBaseName:
                groupedByBaseName[key] = []
            groupedByBaseName[key].append((geoName, geoData))

        allGeometries = []
        for (baseName, parentId), geoList in groupedByBaseName.items():
            if len(geoList) == 1:
                geoName, geoData = geoList[0]
                allChannels = geoData['channels']
                allChannels = self._optimizeChannels(allChannels, sequential=False)
                tdGeometry = TDGeometry(
                    name=geoData['geo'].name,
                    geoObj=geoData['geo'],
                    parent=geoData['geoParent'],
                    tdDmxChannels=allChannels,
                    isSequential=False,
                    sequentialMembers=None
                )
            else:
                sequentialMembers = []
                for geoName, geoData in geoList:
                    sequentialMembers.append(geoData['geo'])

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
        """Optimize the list of channels by merging them based on their activation group and feature."""
        lastActivationGroup = None
        mergeChannelList = []
        returnList = []
        count = 0
        for c in channels:
            attribute = self._getAttributeByName(c.attribute.str_link)
            if attribute:
                feature = attribute.feature.str_link
                activationGroup = attribute.activation_group.str_link
                if activationGroup != lastActivationGroup or activationGroup is None or activationGroup == '':
                    if mergeChannelList:
                        returnList.append(self._createTDDMXChannel(mergeChannelList, sequential, count > 0 and sequential))
                        count += 1
                    mergeChannelList = [c]
                else:
                    mergeChannelList.append(c)
                lastActivationGroup = activationGroup
        if mergeChannelList:
            returnList.append(self._createTDDMXChannel(mergeChannelList, sequential, count > 0 and sequential))
        return returnList

    def _createTDDMXChannel(self, channelList: List[pygdtf.DmxChannel], sequential: bool, mergeWithAbove: bool) -> Optional[TDDMXChannel]:
        """Create a TDDMXChannel from a list of pygdtf.DmxChannel"""
        if not channelList:
            return None
        firstChannel = channelList[0]
        channelName = firstChannel.name
        if sequential:
            # remove the sequential number portion from the name (e.g. Beam_12_Color_Add_R → Beam_Color_Add_R)
            match = SEQNAMEPATTERN.search(channelName)
            if match:
                channelName = channelName[:match.start()] + channelName[match.end():]

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
