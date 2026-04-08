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
    geo: pygdtf.Geometry
    geoParent: pygdtf.Geometry
    channels: List[pygdtf.DmxChannel]


@dataclass
class TDDMXChannel:
    """Information about a single DMX channel"""
    name: str
    channelObj: pygdtf.DmxChannel  # The DMX channel object from the GDTF file
    dmxBreak: int = 1
    dmxOffset: int = 0
    bitDepth: BitDepth = BitDepth.BIT_8
    components: int = 1
    mergeWithAbove: bool = False
    normalized: bool = False  # Whether this channel is normalized
    geoGroup: Optional[str] = None  # The geometry group this channel belongs to, if any
    tdChannelName: Optional[str] = None  # The TouchDesigner channel name, this is mostly removing spaces etc
    channelFunctions: Optional[List[pygdtf.ChannelFunction]] = None  # List of channel functions for this channel


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
    def __init__(self, channelSet: pygdtf.ChannelSet):
        self.name = channelSet.name
        self.dmxRange = (channelSet.dmx_from, channelSet.dmx_to)
        self.physicalRange = (channelSet.physical_from, channelSet.physical_to)
    
    def toDict(self) -> dict:
        return {
            'name': self.name,
            'dmxFrom': self.dmxRange[0].value,
            'dmxTo': self.dmxRange[1].value,
            'physicalFrom': self.physicalRange[0].value,
            'physicalTo': self.physicalRange[1].value,
        }

    @classmethod
    def fromDict(cls, d: dict) -> 'DMXChannelSet':
        obj = object.__new__(cls)
        obj.name = d['name']
        obj.dmxRange = (_ScalarValue(d['dmxFrom']), _ScalarValue(d['dmxTo']))
        obj.physicalRange = (_ScalarValue(d['physicalFrom']), _ScalarValue(d['physicalTo']))
        return obj
        
class DMXChannelFunction:
    def __init__(self, channelFunction: pygdtf.ChannelFunction):

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

        self._value: int = 0

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, value: int):
        self._value = value

    def toDict(self) -> dict:
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
        obj = object.__new__(cls)
        obj.name = d['name']
        obj.dmxRange = (_ScalarValue(d['dmxFrom']), _ScalarValue(d['dmxTo']))
        obj.default = _ScalarValue(d['default'])
        obj.physicalRange = (_ScalarValue(d['physicalFrom']), _ScalarValue(d['physicalTo']))
        obj.channelSets = [DMXChannelSet.fromDict(cs) for cs in d['channelSets']]
        obj._value = 0
        return obj


class DMXValue:
    def __init__(self, x: float, y: float = 0, z: float = 0, w: float = 0, callback=None):
        self._x = x
        self._y = y
        self._z = z
        self._w = w
        self._callback = callback

    @property
    def x(self) -> float:
        return self._x

    @x.setter
    def x(self, value: float):
        self._x = value
        if self._callback:
            self._callback(self)

    @property
    def y(self) -> float:
        return self._y

    @y.setter
    def y(self, value: float):
        self._y = value
        if self._callback:
            self._callback(self)

    @property
    def z(self) -> float:
        return self._z

    @z.setter
    def z(self, value: float):
        self._z = value
        if self._callback:
            self._callback(self)

    @property
    def w(self) -> float:
        return self._w

    @w.setter
    def w(self, value: float):
        self._w = value
        if self._callback:
            self._callback(self)
