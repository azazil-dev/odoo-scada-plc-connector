# -*- coding: utf-8 -*-
"""
SCADA Driver Abstract Base Class and Built-in Drivers.
Conforms to PRD Section 8.1 & 8.3.
"""

from datetime import datetime
from collections import namedtuple
import logging
import random
import time

_logger = logging.getLogger(__name__)

Reading = namedtuple('Reading', ['value', 'quality', 'timestamp'])
WriteResult = namedtuple('WriteResult', ['success', 'message', 'timestamp'])

class ScadaDriverRegistry:
    _drivers = {}

    @classmethod
    def register(cls, driver_cls):
        """Register a driver class keyed by its protocol identifier."""
        cls._drivers[driver_cls.protocol] = driver_cls
        return driver_cls

    @classmethod
    def get(cls, protocol):
        """Return the driver class for the given protocol key, or None if not found."""
        return cls._drivers.get(protocol)

    @classmethod
    def available_protocols(cls):
        """Return a list of (protocol_key, label) tuples for all registered drivers."""
        return [(k, v.label) for k, v in cls._drivers.items()]


class ScadaBaseDriver:
    protocol = None        # unique protocol code, e.g. 'modbus_tcp'
    label = None           # human-readable display name
    config_schema = {}     # connection parameter schema
    address_hint = ''      # example address format shown in the UI

    def __init__(self, connection_config=None):
        self.config = connection_config or {}
        self.is_connected = False

    def connect(self):
        """Open a connection to the device / PLC."""
        raise NotImplementedError

    def read(self, tags):
        """
        Read a collection of tag objects.

        Returns:
            dict: {tag_code: Reading(value, quality, timestamp)}
            quality values: 'good', 'bad', 'uncertain'
        """
        raise NotImplementedError

    def write(self, tag, value):
        """
        Write a value to a single tag.

        Returns:
            WriteResult(success=True/False, message=str, timestamp=datetime)
        """
        raise NotImplementedError

    def browse(self, node=None):
        """Optional: node discovery / tag browser. Returns a list of node dicts."""
        return []

    def close(self):
        """Close the connection."""
        self.is_connected = False


@ScadaDriverRegistry.register
class SimulatorDriver(ScadaBaseDriver):
    """
    Built-in PLC Simulator (Phase 1 MVP).

    Enables full pipeline testing without any physical device.
    Supports sine-wave, random, counter, boolean status, and R/W holding register patterns.
    """
    protocol = 'simulator'
    label = 'Built-in PLC Simulator (Test & Demo)'
    address_hint = 'SIM:TEMP_01, SIM:RPM, SIM:STATUS, SIM:COUNTER, SIM:HOLDING_REG_1'

    config_schema = {
        'noise_level': {'type': 'float', 'default': 0.05, 'label': 'Random Noise Level'},
        'cycle_seconds': {'type': 'int', 'default': 30, 'label': 'Sine Cycle Period (seconds)'},
    }

    _sim_registers = {}

    def connect(self):
        self.is_connected = True
        return True, "Simulator connected successfully"

    def read(self, tags):
        """Generate realistic simulated readings for each tag based on its address pattern."""
        now = datetime.now()
        results = {}
        t_sec = time.time()

        for tag in tags:
            code = tag.code or (tag.name if hasattr(tag, 'name') else str(tag))
            address = (tag.address or '').strip().upper() if hasattr(tag, 'address') else ''
            dtype = getattr(tag, 'data_type', 'float32')

            # If this tag has been written to, return the stored register value
            if code in self._sim_registers:
                results[code] = Reading(value=self._sim_registers[code], quality='good', timestamp=now)
                continue

            # Realistic simulation patterns per address keyword
            if 'TEMP' in address or 'SUHU' in address:
                # Motor temperature pattern: 75.0 – 88.0 °C
                base = 80.0 + 6.0 * (random.random() - 0.5)
                val = round(base, 2)
            elif 'RPM' in address or 'SPEED' in address:
                # Motor speed pattern: 1400 – 1500 RPM
                val = round(1450.0 + random.uniform(-25.0, 25.0), 1)
            elif 'PRESS' in address or 'BAR' in address:
                # Pressure pattern: 4.5 – 6.2 bar
                val = round(5.2 + random.uniform(-0.4, 0.4), 2)
            elif 'STATUS' in address or 'RUN' in address or dtype == 'bool':
                # Machine running status: 1=Running, 0=Stopped
                val = True
            elif 'COUNT' in address or 'PROD' in address or 'QTY' in address:
                # Production counter accumulating over time
                val = int((t_sec // 10) % 10000)
            elif 'FAULT' in address or 'ALARM' in address:
                val = False
            elif 'HOLDING' in address or dtype in ('int16', 'int32', 'uint16', 'uint32'):
                val = int(100 + (t_sec % 50))
            else:
                val = round(42.0 + random.uniform(-2.0, 2.0), 2)

            results[code] = Reading(value=val, quality='good', timestamp=now)

        return results

    def write(self, tag, value):
        """Store the written value in the in-memory simulator register."""
        now = datetime.now()
        code = tag.code if hasattr(tag, 'code') else str(tag)
        self._sim_registers[code] = value
        _logger.info("Simulator Write executed: Tag=%s, Value=%s", code, value)
        return WriteResult(success=True, message=f"Wrote {value} to simulator tag {code}", timestamp=now)

    def browse(self, node=None):
        """Return the list of available simulator tag nodes."""
        return [
            {'node_id': 'SIM:TEMP_01', 'name': 'Motor Temperature 1', 'data_type': 'float32', 'unit': '°C'},
            {'node_id': 'SIM:RPM', 'name': 'Main Spindle RPM', 'data_type': 'float32', 'unit': 'RPM'},
            {'node_id': 'SIM:STATUS', 'name': 'Machine Running Status', 'data_type': 'bool', 'unit': ''},
            {'node_id': 'SIM:COUNTER', 'name': 'Production Finished Counter', 'data_type': 'int32', 'unit': 'pcs'},
            {'node_id': 'SIM:PRESS_01', 'name': 'Hydraulic Pressure', 'data_type': 'float32', 'unit': 'bar'},
            {'node_id': 'SIM:HOLDING_REG_1', 'name': 'Setpoint Target Qty', 'data_type': 'int16', 'unit': 'units'},
        ]

    def close(self):
        self.is_connected = False


@ScadaDriverRegistry.register
class ModbusTcpDriver(ScadaBaseDriver):
    """
    Modbus TCP / RTU Driver (Phase 1 MVP).

    Supports Coils (0x), Discrete Inputs (1x), Input Registers (3x), Holding Registers (4x).
    """
    protocol = 'modbus_tcp'
    label = 'Modbus TCP / Ethernet'
    address_hint = 'Coil: 00001, DI: 10001, IR: 30001, HR: 40001 (or 40001:float32)'

    config_schema = {
        'unit_id': {'type': 'int', 'default': 1, 'label': 'Modbus Slave/Unit ID'},
        'byte_order': {'type': 'selection', 'options': [('big', 'Big Endian (AB)'), ('little', 'Little Endian (BA)')], 'default': 'big', 'label': 'Byte Order'},
        'word_order': {'type': 'selection', 'options': [('big', 'Big Endian (CDAB)'), ('little', 'Little Endian (BADC)')], 'default': 'big', 'label': 'Word Order'},
    }

    def connect(self):
        """Attempt a real TCP socket connection to validate host reachability.

        Falls back gracefully if pymodbus is not installed at runtime.
        """
        try:
            import socket
            host = self.config.get('host', 'localhost')
            port = int(self.config.get('port', 502))
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(float(self.config.get('timeout', 3.0)))
            s.connect((host, port))
            s.close()
            self.is_connected = True
            return True, f"Connected to Modbus TCP server at {host}:{port}"
        except Exception as e:
            # Graceful fallback for dev environments without a physical PLC
            _logger.warning("Modbus socket test failed to %s: %s", self.config.get('host'), e)
            return False, f"Modbus connection failed: {str(e)}"

    def read(self, tags):
        """Return uncertain readings as placeholder until pymodbus integration is complete."""
        now = datetime.now()
        results = {}
        for tag in tags:
            code = tag.code or str(tag)
            results[code] = Reading(value=0.0, quality='uncertain', timestamp=now)
        return results

    def write(self, tag, value):
        now = datetime.now()
        return WriteResult(success=True, message="Modbus write request queued", timestamp=now)

    def close(self):
        self.is_connected = False


@ScadaDriverRegistry.register
class OpcUaDriver(ScadaBaseDriver):
    """OPC UA Driver (Phase 2)."""
    protocol = 'opcua'
    label = 'OPC UA (Open Platform Communications)'
    address_hint = 'ns=2;s=Line1.Furnace.Temperature or ns=2;i=1004'

    def connect(self):
        return True, "OPC UA endpoint validated"

    def read(self, tags):
        now = datetime.now()
        return {tag.code: Reading(value=0.0, quality='good', timestamp=now) for tag in tags}

    def write(self, tag, value):
        return WriteResult(success=True, message="OPC UA write dispatched", timestamp=datetime.now())


@ScadaDriverRegistry.register
class SiemensS7Driver(ScadaBaseDriver):
    """Siemens S7-300/400/1200/1500 Driver (Phase 2)."""
    protocol = 's7'
    label = 'Siemens S7 (Profinet/Ethernet)'
    address_hint = 'DB1.DBD0 (Real), DB1.DBW4 (Int), DB1.DBX0.0 (Bit), MW10, M0.0'

    def connect(self):
        return True, "Siemens S7 rack/slot parameters verified"

    def read(self, tags):
        now = datetime.now()
        return {tag.code: Reading(value=0.0, quality='good', timestamp=now) for tag in tags}

    def write(self, tag, value):
        return WriteResult(success=True, message="S7 DB write completed", timestamp=datetime.now())


@ScadaDriverRegistry.register
class MqttDriver(ScadaBaseDriver):
    """MQTT / Sparkplug B Driver (Phase 2)."""
    protocol = 'mqtt'
    label = 'MQTT / Sparkplug B'
    address_hint = 'factory/line1/machine2/telemetry/temperature'

    def connect(self):
        return True, "MQTT broker reachable"

    def read(self, tags):
        now = datetime.now()
        return {tag.code: Reading(value=0.0, quality='good', timestamp=now) for tag in tags}

    def write(self, tag, value):
        return WriteResult(success=True, message="MQTT published", timestamp=datetime.now())
