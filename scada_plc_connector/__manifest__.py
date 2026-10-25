# -*- coding: utf-8 -*-
{
    'name': "SCADA PLC Connector",
    'summary': "Industrial Machine Integration Platform, PLC, IoT Gateway & Real-time Telemetry for Odoo 19 CE",
    'description': """
SCADA PLC Connector for Odoo 19 Community Edition
===================================================
Turns Odoo 19 CE into a central configuration hub and data consumer for factory machines.
Supports industrial protocols (Modbus TCP, OPC UA, Siemens S7, MQTT, EtherNet/IP)
without coding through the Odoo UI.

Key Features:
-------------
1. Protocol-Agnostic & Driver SDK: Extensible driver plugins with a standard interface.
2. Gateway Management: Secure API Key authentication (SHA-256), heartbeat, store-and-forward buffer.
3. Tag & Device Management: Data types bool, int, float, string, scale, offset, safe_eval formula.
4. Rule Engine & Alarms: Threshold conditions, minimum duration, hysteresis, debounce, automated maintenance request creation.
5. Safe Write Control (IEC 62443): Writable tag whitelist, safe value bounds, global Read-Only mode, and full audit log.
6. REST API Ingest: High-throughput batch endpoint /scada/api/v1/ingest and dynamic ETag config retrieval.
7. Built-in Simulator: Full pipeline testing without a physical PLC.
    """,
    'author': "Arif N Ramadhan",
    'website': "https://www.niits.id",
    'category': 'Manufacturing/IoT',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'mrp', 'maintenance'],
    'data': [
        'security/scada_security.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/scada_views.xml',
        'views/scada_menus.xml',
        'data/demo_scada_data.xml',
    ],
    'demo': [
        'data/demo_scada_data.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
