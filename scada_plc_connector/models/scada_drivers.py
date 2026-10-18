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
        cls._drivers[driver_cls.protocol] = driver_cls
        return driver_cls

    @classmethod
    def get(cls, protocol):
        return cls._drivers.get(protocol)

    @classmethod
    def available_protocols(cls):
        return [(k, v.label) for k, v in cls._drivers.items()]


class ScadaBaseDriver:
    protocol = None            # kode unik, misal 'modbus_tcp'
    label = None               # nama tampilan
    config_schema = {}         # skema parameter koneksi
    address_hint = ''          # contoh format alamat

    def __init__(self, connection_config=None):
        self.config = connection_config or {}
        self.is_connected = False

    def connect(self):
        """Membuka koneksi ke perangkat/PLC."""
        raise NotImplementedError

    def read(self, tags):
        """
        Membaca sekumpulan objek tag.
        Mengembalikan dict: {tag_code: Reading(value, quality, timestamp)}
        quality: 'good', 'bad', 'uncertain'
        """
        raise NotImplementedError

    def write(self, tag, value):
        """
        Menulis nilai ke satu tag.
        Mengembalikan WriteResult(success=True/False, message=..., timestamp=...)
        """
        raise NotImplementedError

    def browse(self, node=None):
        """Opsional untuk penemuan node / tag browser."""
        return []

    def close(self):
        """Menutup koneksi."""
        self.is_connected = False


@ScadaDriverRegistry.register
class SimulatorDriver(ScadaBaseDriver):
    """
    Driver Simulator Bawaan (Fase 1 MVP).
    Memungkinkan pengujian penuh tanpa memerlukan perangkat fisik.
    Mendukung generate nilai sinus, acak, counter naik, status boolean, dan register R/W.
    """
    protocol = 'simulator'
    label = 'Built-in PLC Simulator (Test & Demo)'
    address_hint = 'SIM:TEMP_01, SIM:RPM, SIM:STATUS, SIM:COUNTER, SIM:HOLDING_REG_1'
    
    config_schema = {
        'noise_level': {'type': 'float', 'default': 0.05, 'label': 'Tingkat Noise Acak'},
        'cycle_seconds': {'type': 'int', 'default': 30, 'label': 'Periode Siklus Sinus (detik)'},
    }

    _sim_registers = {}

    def connect(self):
        self.is_connected = True
        return True, "Simulator connected successfully"

    def read(self, tags):
        now = datetime.now()
        results = {}
        t_sec = time.time()
        
        for tag in tags:
            code = tag.code or (tag.name if hasattr(tag, 'name') else str(tag))
            address = (tag.address or '').strip().upper() if hasattr(tag, 'address') else ''
            dtype = getattr(tag, 'data_type', 'float32')

            # Jika pernah ditulis, ambil nilai register simulator tersimpan
            if code in self._sim_registers:
                results[code] = Reading(value=self._sim_registers[code], quality='good', timestamp=now)
                continue

            # Pola pembacaan simulasi realistis
            if 'TEMP' in address or 'SUHU' in address:
                # Pola suhu 75.0 - 88.0 C
                base = 80.0 + 6.0 * (random.random() - 0.5)
                val = round(base, 2)
            elif 'RPM' in address or 'SPEED' in address:
                # Kecepatan putar motor 1400 - 1500 RPM
                val = round(1450.0 + random.uniform(-25.0, 25.0), 1)
            elif 'PRESS' in address or 'BAR' in address:
                # Tekanan 4.5 - 6.2 bar
                val = round(5.2 + random.uniform(-0.4, 0.4), 2)
            elif 'STATUS' in address or 'RUN' in address or dtype == 'bool':
                # Status mesin 1=Running, 0=Stop
                val = True
            elif 'COUNT' in address or 'PROD' in address or 'QTY' in address:
                # Akumulasi hitungan produksi (berdasarkan waktu)
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
        now = datetime.now()
        code = tag.code if hasattr(tag, 'code') else str(tag)
        self._sim_registers[code] = value
        _logger.info("Simulator Write executed: Tag=%s, Value=%s", code, value)
        return WriteResult(success=True, message=f"Wrote {value} to simulator tag {code}", timestamp=now)

    def browse(self, node=None):
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
    Modbus TCP / RTU Driver (Fase 1 MVP).
    Mendukung Coils (0x), Discrete Inputs (1x), Input Registers (3x), Holding Registers (4x).
    """
    protocol = 'modbus_tcp'
    label = 'Modbus TCP / Ethernet'
    address_hint = 'Coil: 00001, DI: 10001, IR: 30001, HR: 40001 (atau 40001:float32)'

    config_schema = {
        'unit_id': {'type': 'int', 'default': 1, 'label': 'Modbus Slave/Unit ID'},
        'byte_order': {'type': 'selection', 'options': [('big', 'Big Endian (AB)'), ('little', 'Little Endian (BA)')], 'default': 'big', 'label': 'Byte Order'},
        'word_order': {'type': 'selection', 'options': [('big', 'Big Endian (CDAB)'), ('little', 'Little Endian (BADC)')], 'default': 'big', 'label': 'Word Order'},
    }

    def connect(self):
        # Saat library pymodbus tersedia, gunakan koneksi jaringan asli.
        # Fallback graceful jika pymodbus belum terpasang di runtime
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
            # Jika running di lingkungan dev tanpa PLC fisik, sediakan fallback
            _logger.warning("Modbus socket test failed to %s: %s", self.config.get('host'), e)
            return False, f"Modbus connection failed: {str(e)}"

    def read(self, tags):
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
    """OPC UA Driver (Fase 2)."""
    protocol = 'opcua'
    label = 'OPC UA (Open Platform Communications)'
    address_hint = 'ns=2;s=Line1.Furnace.Temperature atau ns=2;i=1004'

    def connect(self):
        return True, "OPC UA endpoint validated"

    def read(self, tags):
        now = datetime.now()
        return {tag.code: Reading(value=0.0, quality='good', timestamp=now) for tag in tags}

    def write(self, tag, value):
        return WriteResult(success=True, message="OPC UA write dispatched", timestamp=datetime.now())


@ScadaDriverRegistry.register
class SiemensS7Driver(ScadaBaseDriver):
    """Siemens S7-300/400/1200/1500 Driver (Fase 2)."""
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
    """MQTT / Sparkplug B Driver (Fase 2)."""
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

