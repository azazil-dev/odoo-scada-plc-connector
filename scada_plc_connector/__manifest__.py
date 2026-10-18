# -*- coding: utf-8 -*-
{
    'name': "SCADA PLC Connector",
    'summary': "Platform Integrasi Mesin Industri, PLC, IoT Gateway & Telemetri Real-time Odoo 17 CE",
    'description': """
SCADA PLC Connector untuk Odoo 17 Community Edition
===================================================
Menjadikan Odoo 17 CE sebagai pusat konfigurasi dan konsumen data mesin pabrik.
Mendukung protokol industri (Modbus TCP, OPC UA, Siemens S7, MQTT, EtherNet/IP)
tanpa coding melalui UI Odoo.

Fitur Utama:
------------
1. Protocol-Agnostic & Driver SDK: Driver plugin yang dapat diekstensi dengan antarmuka standar.
2. Gateway Management: Otentikasi API Key aman (SHA-256), heartbeat, buffer store-and-forward.
3. Manajemen Tag & Perangkat: Tipe data bool, int, float, string, scale, offset, formula safe_eval.
4. Rule Engine & Alarm: Kondisi ambang batas, durasi minimum, histeresis, debounce, otomatisasi maintenance request.
5. Kontrol Tulis Aman (IEC 62443): Whitelist tag writable, batas nilai aman, mode Read-Only global, dan audit log lengkap.
6. REST API Ingest: Endpoint batch berkecepatan tinggi /scada/api/v1/ingest dan penarikan konfigurasi dinamis ETag.
7. Simulator Bawaan: Pengujian lengkap tanpa PLC fisik.
    """,
    'author': "Arif N Ramadhan",
    'website': "https://www.niits.id",
    'category': 'Manufacturing/IoT',
    'version': '17.0.1.0.0',
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
