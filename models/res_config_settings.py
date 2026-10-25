# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    scada_enable_multi_company = fields.Boolean(
        string="Multi-Company SCADA",
        config_parameter='scada_plc_connector.enable_multi_company',
        default=False,
        help="Enable data isolation for SCADA assets (devices, gateways, tags, connections) per company entity."
    )

    scada_location_mode = fields.Selection([
        ('single', 'Single Location (Single Plant / Site)'),
        ('multi', 'Multi-Location (Multi-Plant / Multi-Site)'),
    ], string="Location Mode",
        config_parameter='scada_plc_connector.location_mode',
        default='single',
        help="Multi-location mode enables assigning connections and gateways per plant site."
    )

    scada_history_backend = fields.Selection([
        ('postgresql', 'Standard PostgreSQL Table (Odoo Default)'),
        ('timescaledb', 'TimescaleDB Hypertable Engine (Time-series Optimized)'),
    ], string="History Storage Backend",
        config_parameter='scada_plc_connector.history_backend',
        default='postgresql',
        help="Enable TimescaleDB if the PostgreSQL instance has the timescale extension installed for high-speed automatic aggregation."
    )

    scada_plc_write_mode = fields.Selection([
        ('enabled', 'Enabled (Allow Write Commands to Registered Tags)'),
        ('readonly', 'Global Read-Only Mode (Immediately Lock All PLC Writes)'),
    ], string="PLC Write Control Mode",
        config_parameter='scada_plc_connector.plc_write_mode',
        default='enabled',
        help="Global kill-switch to instantly disable all write commands to PLC registers for plant safety."
    )

    scada_iec62443_profile = fields.Boolean(
        string="IEC 62443 Security Profile",
        config_parameter='scada_plc_connector.iec62443_profile',
        default=True,
        help="Enforce immutable audit logs, min/max write value validation, and SHA-256 token authentication."
    )

    scada_retention_days = fields.Integer(
        string="Telemetry History Retention (Days)",
        config_parameter='scada_plc_connector.retention_days',
        default=30,
        help="Tag value history records older than this number of days will be automatically purged by a cron job."
    )

    scada_ingest_rate_limit = fields.Integer(
        string="Max Ingest Batch Size (Tag Values / Batch)",
        config_parameter='scada_plc_connector.ingest_rate_limit',
        default=5000,
        help="Maximum telemetry batch size allowed in a single HTTP POST to the ingest endpoint."
    )
