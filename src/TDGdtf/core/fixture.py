"""Data classes representing a parsed GDTF fixture for use in TouchDesigner."""
import pygdtf
from dataclasses import dataclass
from typing import List, Any, Optional, TypedDict
from enum import IntEnum


class BitDepth(IntEnum):
    """Enum for DMX channel bit depth"""
    BIT_8 = 8
    BIT_16 = 16
    BIT_24 = 24
    BIT_32 = 32


class GeoData(TypedDict):
    """Intermediate grouping of a geometry and its raw GDTF DMX channels."""

    geo: pygdtf.Geometry
    geoParent: pygdtf.Geometry
    channels: List[pygdtf.DmxChannel]


@dataclass
class TDDMXChannel:
    """Information about a single DMX channel"""
    name: str
    channelObj: pygdtf.DmxChannel  # The DMX channel object from the GDTF file
    dmxBreak: int = 1
    dmxOffset: Optional[List[int]] = None  # DMX byte offsets from pygdtf; length determines bit depth
    bitDepth: BitDepth = BitDepth.BIT_8
    components: int = 1
    mergeWithAbove: bool = False
    normalized: bool = False  # Whether this channel is normalized
    geoGroup: Optional[str] = None  # The geometry group this channel belongs to, if any
    geoType: str = 'primitive'  # 'point' for sequential geometries, 'primitive' otherwise
    instances: int = 1  # Number of sequential geometry members this channel drives
    tdChannelName: Optional[str] = None  # The TouchDesigner channel name, this is mostly removing spaces etc
    channelFunctions: Optional[List[pygdtf.ChannelFunction]] = None  # List of channel functions for this channel
    masterControlled: bool = False  # True when LogicalChannel.master is Grand


@dataclass
class TDGeometry:
    """Information about a single geometry"""
    name: str
    geoObj: pygdtf.Geometry  # The geometry object from the GDTF file
    parent: pygdtf.Geometry
    isSequential: bool = False
    sequentialMembers: Optional[List[pygdtf.Geometry]] = None  # List of geometries that are members of this sequence
    tdDmxChannels: Optional[List[TDDMXChannel]] = None  # List of DMX channels that are part of this geometry


@dataclass
class DMXModeInfo:
    """Information about a DMX mode"""
    name: str
    description: str
    tdGeometries: Optional[List[TDGeometry]] = None  # Which geometries are used in this mode
    tdChannels: Optional[List[TDDMXChannel]] = None  # List of DMX channels in this mode
    totalTdChannels: Optional[int] = 0  # Total number of DMX channels in this mode


@dataclass
class TouchDesignerFixture:
    """Complete fixture data structure for TouchDesigner"""
    name: str
    manufacturer: str
    attributes: List[Any]
    dmxModes: List[DMXModeInfo]  # All available DMX modes

class _ScalarValue:
    """Minimal stand-in for pygdtf numeric range objects (.value attribute)."""
    def __init__(self, value):
        self.value = value

class DMXChannelSet:
    """A named range within a channel function mapping DMX bytes to a physical value span."""

    def __init__(self, channelSet: pygdtf.ChannelSet):
        """Build from a live pygdtf ChannelSet object.

        Args:
            channelSet: pygdtf ChannelSet to read name and DMX/physical ranges from.
        """
        self.name = channelSet.name
        self.dmxRange = (channelSet.dmx_from, channelSet.dmx_to)
        self.physicalRange = (channelSet.physical_from, channelSet.physical_to)
    
    def toDict(self) -> dict:
        """Serialise to a plain dict for storage."""
        return {
            'name': self.name,
            'dmxFrom': self.dmxRange[0].value,
            'dmxTo': self.dmxRange[1].value,
            'physicalFrom': self.physicalRange[0].value,
            'physicalTo': self.physicalRange[1].value,
        }

    @classmethod
    def fromDict(cls, d: dict) -> 'DMXChannelSet':
        """Reconstruct from a plain dict as produced by toDict.

        Args:
            d: dict from toDict.
        """
        obj = object.__new__(cls)
        obj.name = d['name']
        obj.dmxRange = (_ScalarValue(d['dmxFrom']), _ScalarValue(d['dmxTo']))
        obj.physicalRange = (_ScalarValue(d['physicalFrom']), _ScalarValue(d['physicalTo']))
        return obj

class DMXChannelFunction:
    """One functional range of a logical DMX channel (e.g. 'Dimmer' 0-255)."""

    def __init__(self, channelFunction: pygdtf.ChannelFunction):
        """Build from a live pygdtf ChannelFunction object.

        Args:
            channelFunction: pygdtf ChannelFunction to read ranges and channel sets from.
        """

        def _loadChannelSets():
            cSets = []
            for channelSet in channelFunction.channel_sets:
                if len(channelSet.name):
                    cSets.append(DMXChannelSet(channelSet))
            return cSets

        self.name = channelFunction.name
        self.dmxRange = (channelFunction.dmx_from, channelFunction.dmx_to)
        self.default = channelFunction.default
        self.physicalRange = (channelFunction.physical_from, channelFunction.physical_to)
        self.channelSets: List[DMXChannelSet] = _loadChannelSets()

        self.value: int = 0

    def toDict(self) -> dict:
        """Serialise to a plain dict for storage."""
        return {
            'name': self.name,
            'dmxFrom': self.dmxRange[0].value,
            'dmxTo': self.dmxRange[1].value,
            'default': self.default.value,
            'physicalFrom': self.physicalRange[0].value,
            'physicalTo': self.physicalRange[1].value,
            'channelSets': [cs.toDict() for cs in self.channelSets],
        }

    @classmethod
    def fromDict(cls, d: dict) -> 'DMXChannelFunction':
        """Reconstruct from a plain dict as produced by toDict.

        Args:
            d: dict from toDict.
        """
        obj = object.__new__(cls)
        obj.name = d['name']
        obj.dmxRange = (_ScalarValue(d['dmxFrom']), _ScalarValue(d['dmxTo']))
        obj.default = _ScalarValue(d['default'])
        obj.physicalRange = (_ScalarValue(d['physicalFrom']), _ScalarValue(d['physicalTo']))
        obj.channelSets = [DMXChannelSet.fromDict(cs) for cs in d['channelSets']]
        obj.value = 0
        return obj


class DMXValue:
    """Four-component raw DMX value (x/y/z/w)."""

    def __init__(self, x: float, y: float = 0, z: float = 0, w: float = 0):
        """Initialise with raw DMX component values.

        Args:
            x: Primary DMX component (always used).
            y: Second component for 16-bit or wider channels.
            z: Third component for 24-bit or wider channels.
            w: Fourth component for 32-bit channels.
        """
        self.x = x
        self.y = y
        self.z = z
        self.w = w

    def __repr__(self) -> str:
        return f"DMXValue(x={self.x}, y={self.y}, z={self.z}, w={self.w})"
