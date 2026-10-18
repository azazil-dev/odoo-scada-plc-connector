# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    scada_enable_multi_company = fields.Boolean(
        string="Multi-Company SCADA",
        config_parameter='scada_plc_connector.enable_multi_company',
        default=False,
        help="Mengaktifkan isolasi data SCADA (perangkat, gateway, tag, koneksi) per entitas perusahaan."
    )

    scada_location_mode = fields.Selection([
        ('single', 'Lokasi Tunggal (Single Plant / Site)'),
        ('multi', 'Multi-Lokasi (Multi Plant / Multi-Site)'),
    ], string="Mode Lokasi",
        config_parameter='scada_plc_connector.location_mode',
        default='single',
        help="Mode multi-lokasi membuka penugasan koneksi dan gateway per site pabrik."
    )

    scada_history_backend = fields.Selection([
        ('postgresql', 'Standard PostgreSQL Table (Bawaan Odoo)'),
        ('timescaledb', 'TimescaleDB Hypertable Engine (Optimasi Time-series)'),
    ], string="Backend Penyimpanan Histori",
        config_parameter='scada_plc_connector.history_backend',
        default='postgresql',
        help="Aktifkan TimescaleDB jika PostgreSQL memiliki ekstensi timescale terpasang untuk agregasi otomatis kecepatan tinggi."
    )

    scada_plc_write_mode = fields.Selection([
        ('enabled', 'Aktif (Izinkan Perintah Tulis ke Tag Terdaftar)'),
        ('readonly', 'Global Read-Only Mode (Kunci Semua Penulisan PLC Segera)'),
    ], string="Mode Kontrol Penulisan PLC",
        config_parameter='scada_plc_connector.plc_write_mode',
        default='enabled',
        help="Global kill-switch untuk seketika mematikan segala perintah tulis ke register PLC demi keselamatan pabrik."
    )

    scada_iec62443_profile = fields.Boolean(
        string="Profil Keamanan IEC 62443",
        config_parameter='scada_plc_connector.iec62443_profile',
        default=True,
        help="Wajibkan audit log tak dapat diubah, validasi batas min/max nilai tulis, dan otentikasi token SHA-256."
    )

    scada_retention_days = fields.Integer(
        string="Masa Retensi Histori Telemetri (Hari)",
        config_parameter='scada_plc_connector.retention_days',
        default=30,
        help="Data nilai tag histori yang lebih tua dari jumlah hari ini akan dibersihkan otomatis oleh cron job."
    )

    scada_ingest_rate_limit = fields.Integer(
        string="Batas Maksimum Ingest Batch (Tag Values / Batch)",
        config_parameter='scada_plc_connector.ingest_rate_limit',
        default=5000,
        help="Ukuran batch maksimum telemetri yang diizinkan dalam satu HTTP POST ke endpoint ingest."
    )

