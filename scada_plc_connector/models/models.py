# -*- coding: utf-8 -*-
"""
Core Data Models for SCADA PLC Connector.
Implements:
- scada.gateway (FR-G1 - FR-G6)
- scada.connection (FR-C1 - FR-C7)
- scada.device (FR-D1 - FR-D4)
- scada.tag (FR-T1 - FR-T10)
- scada.tag.last (FR-S1)
- scada.tag.value (FR-S2 - FR-S6)
- scada.tag.aggregate (FR-S4)
- scada.rule (FR-R1 - FR-R6)
- scada.action (FR-A1 - FR-A8)
- scada.mapping (Section 6.6)
- scada.alarm (FR-R4)
- scada.write.request (FR-A3, Section 7.3)
- scada.log (Section 7.3, Section 7.6)
"""

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval
from .scada_drivers import ScadaDriverRegistry
import secrets
import hashlib
import json
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


# =============================================================================
# 1. GATEWAY MANAGEMENT (scada.gateway)
# =============================================================================
class ScadaGateway(models.Model):
    _name = 'scada.gateway'
    _description = 'Edge IoT / SCADA Gateway'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Gateway Name", required=True, tracking=True)
    code = fields.Char(string="Unique Code", required=True, copy=False, default=lambda self: 'GW-' + secrets.token_hex(4).upper())
    mode = fields.Selection([
        ('gateway', 'Remote Edge Gateway (REST/JSON Service)'),
        ('embedded', 'Embedded Odoo Worker (Local Driver Polling)'),
    ], string="Operating Mode", default='gateway', required=True, tracking=True)

    status = fields.Selection([
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('warning', 'Degraded / Warning'),
    ], string="Gateway Status", default='offline', compute='_compute_status', store=True, tracking=True)

    api_key_hash = fields.Char(string="API Key Hash", copy=False, readonly=True)
    api_key_display = fields.Char(string="API Key (Copy Now)", copy=False, readonly=True,
                                  help="Secret authentication key for the Gateway. Displayed only once upon generation.")

    last_heartbeat = fields.Datetime(string="Last Heartbeat", readonly=True)
    version = fields.Char(string="Gateway Version", readonly=True)
    host_os = fields.Char(string="Host OS", readonly=True)
    active_tags_count = fields.Integer(string="Active Tags", compute='_compute_tag_stats')
    buffer_queue_size = fields.Integer(string="Store-and-Forward Buffer", default=0, readonly=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)

    connection_ids = fields.One2many('scada.connection', 'gateway_id', string="Attached Connections")
    log_ids = fields.One2many('scada.log', 'gateway_id', string="Gateway Logs")

    @api.depends('last_heartbeat')
    def _compute_status(self):
        """Derive gateway status from last heartbeat timestamp and buffer size."""
        now = fields.Datetime.now()
        for rec in self:
            if not rec.last_heartbeat:
                rec.status = 'offline'
            elif (now - rec.last_heartbeat).total_seconds() > 180:
                rec.status = 'offline'
            elif rec.buffer_queue_size > 500:
                rec.status = 'warning'
            else:
                rec.status = 'online'

    def _compute_tag_stats(self):
        """Count active tags across all connections belonging to this gateway."""
        for rec in self:
            tags = self.env['scada.tag'].search_count([
                ('connection_id.gateway_id', '=', rec.id),
                ('active', '=', True)
            ])
            rec.active_tags_count = tags

    def action_generate_api_key(self):
        """Generate a new API Key and store it as a SHA-256 hash (FR-G2)."""
        self.ensure_one()
        raw_key = 'scada_gw_' + secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        self.write({
            'api_key_hash': key_hash,
            'api_key_display': raw_key,
        })
        self.env['scada.log'].create({
            'log_type': 'security',
            'level': 'warning',
            'message': f"API Key regenerated for gateway '{self.name}'.",
            'gateway_id': self.id,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('API Key Generated'),
                'message': _('Copy the API Key now: %s. This value will not be stored in plain text.') % raw_key,
                'type': 'warning',
                'sticky': True,
            }
        }


# =============================================================================
# 2. PLC CONNECTION (scada.connection)
# =============================================================================
class ScadaConnection(models.Model):
    _name = 'scada.connection'
    _description = 'PLC / SCADA Connection'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Connection Name", required=True, tracking=True)
    code = fields.Char(string="Unique Code", required=True, copy=False, default=lambda self: 'CONN-' + secrets.token_hex(3).upper())
    gateway_id = fields.Many2one('scada.gateway', string="Responsible Gateway", required=True, tracking=True)

    protocol = fields.Selection([
        ('simulator', 'Built-in PLC Simulator'),
        ('modbus_tcp', 'Modbus TCP / Ethernet'),
        ('opcua', 'OPC UA'),
        ('s7', 'Siemens S7 (Profinet)'),
        ('mqtt', 'MQTT / Sparkplug B'),
    ], string="Industrial Protocol", default='simulator', required=True, tracking=True)

    host = fields.Char(string="Host / IP Address / Broker", default="127.0.0.1", required=True)
    port = fields.Integer(string="Port", default=502, required=True)
    timeout = fields.Float(string="Timeout (seconds)", default=3.0)
    retry_count = fields.Integer(string="Max Retries", default=3)
    poll_interval_default = fields.Float(string="Default Poll Interval (seconds)", default=1.0)

    # Protocol-specific parameters (stored as JSON)
    protocol_params = fields.Text(string="Custom Parameters (JSON)", default="{}")
    unit_id = fields.Integer(string="Modbus Slave/Unit ID", default=1)
    s7_rack = fields.Integer(string="S7 Rack", default=0)
    s7_slot = fields.Integer(string="S7 Slot", default=1)
    mqtt_topic_prefix = fields.Char(string="MQTT Topic Prefix", default="factory/line1")

    state = fields.Selection([
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('error', 'Error'),
    ], string="Connection Status", default='offline', tracking=True)

    last_seen = fields.Datetime(string="Last Active", readonly=True)
    latency_ms = fields.Float(string="Latency (ms)", default=0.0, readonly=True)
    error_count = fields.Integer(string="Total Errors", default=0, readonly=True)
    last_error_message = fields.Text(string="Last Error Message", readonly=True)

    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)

    device_ids = fields.One2many('scada.device', 'connection_id', string="Devices / Machines")
    tag_ids = fields.One2many('scada.tag', 'connection_id', string="Tag List")

    def action_test_connection(self):
        """FR-C3: Run a live connection test through the driver registry (local or remote)."""
        self.ensure_one()
        driver_cls = ScadaDriverRegistry.get(self.protocol)
        if not driver_cls:
            raise UserError(_("No driver found for protocol '%s'.") % self.protocol)

        cfg = {
            'host': self.host,
            'port': self.port,
            'timeout': self.timeout,
            'unit_id': self.unit_id,
            's7_rack': self.s7_rack,
            's7_slot': self.s7_slot,
        }
        driver = driver_cls(cfg)
        start_time = datetime.now()
        try:
            success, msg = driver.connect()
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000.0
            if success:
                self.write({
                    'state': 'online',
                    'last_seen': fields.Datetime.now(),
                    'latency_ms': round(elapsed_ms, 2),
                    'last_error_message': False,
                })
                self.env['scada.log'].create({
                    'log_type': 'connection',
                    'level': 'info',
                    'message': f"Connection test '{self.name}' SUCCEEDED: {msg} ({elapsed_ms:.1f} ms)",
                    'connection_id': self.id,
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Connection Successful'),
                        'message': _("%s (Latency: %.1f ms)") % (msg, elapsed_ms),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                self.write({
                    'state': 'error',
                    'error_count': self.error_count + 1,
                    'last_error_message': msg,
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Connection Failed'),
                        'message': msg,
                        'type': 'danger',
                        'sticky': True,
                    }
                }
        except Exception as e:
            self.write({
                'state': 'error',
                'error_count': self.error_count + 1,
                'last_error_message': str(e),
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Test Error'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }


# =============================================================================
# 3. DEVICE / MACHINE (scada.device)
# =============================================================================
class ScadaDevice(models.Model):
    _name = 'scada.device'
    _description = 'Plant Device / Machine'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Device / Machine Name", required=True, tracking=True)
    code = fields.Char(string="Asset Number / Code", required=True, copy=False)
    connection_id = fields.Many2one('scada.connection', string="Primary Connection", required=True, tracking=True)
    description = fields.Text(string="Description / Location")

    # Integration with Work Center & Maintenance Equipment (FR-D2)
    workcenter_id = fields.Many2one('mrp.workcenter', string="Related Work Center (MRP)", tracking=True)
    equipment_id = fields.Many2one('maintenance.equipment', string="Related Equipment (Maintenance)", tracking=True)

    state = fields.Selection([
        ('running', 'Running'),
        ('idle', 'Idle'),
        ('stopped', 'Stopped'),
        ('fault', 'Fault'),
    ], string="Machine Status", default='running', tracking=True)

    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)

    tag_ids = fields.One2many('scada.tag', 'device_id', string="Machine Tag List")
    alarm_ids = fields.One2many('scada.alarm', 'device_id', string="Active Alarms")


# =============================================================================
# 4. TAG MANAGEMENT (scada.tag)
# =============================================================================
class ScadaTag(models.Model):
    _name = 'scada.tag'
    _description = 'PLC / SCADA Tag Definition'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'display_name'

    name = fields.Char(string="Tag Name", required=True, tracking=True)
    code = fields.Char(string="Unique Tag Code", required=True, copy=False, tracking=True)
    display_name = fields.Char(string="Display Name", compute='_compute_display_name', store=True)

    connection_id = fields.Many2one('scada.connection', string="Connection", required=True, ondelete='cascade')
    device_id = fields.Many2one('scada.device', string="Related Device / Machine", ondelete='set null')

    address = fields.Char(string="Register Address / Topic", required=True, help="Examples: 40001, DB1.DBD0, SIM:TEMP_01, ns=2;s=Temperature")
    data_type = fields.Selection([
        ('bool', 'Boolean (Bit / Coil)'),
        ('int16', 'Integer 16-Bit'),
        ('int32', 'Integer 32-Bit'),
        ('uint16', 'Unsigned Integer 16-Bit'),
        ('uint32', 'Unsigned Integer 32-Bit'),
        ('float32', 'Float 32-Bit (IEEE 754)'),
        ('float64', 'Double 64-Bit'),
        ('string', 'String / ASCII'),
    ], string="Data Type", default='float32', required=True)

    mode = fields.Selection([
        ('read', 'Read-Only'),
        ('write', 'Write-Only'),
        ('read_write', 'Read / Write'),
    ], string="Access Mode", default='read', required=True)

    unit = fields.Char(string="Unit", help="Examples: °C, bar, RPM, pcs, A, V, kW")
    description = fields.Text(string="Description")

    # Value transformation (FR-T2)
    scale = fields.Float(string="Scale (Multiplier)", default=1.0)
    offset = fields.Float(string="Offset (Shift)", default=0.0)
    formula = fields.Char(string="Custom Formula", help="safe_eval expression. Example: value * 0.1 - 5.0")

    # Recording strategy (FR-T3)
    record_strategy = fields.Selection([
        ('periodic', 'Periodic (Fixed Interval)'),
        ('on_change', 'On-Change (Record Only When Changed)'),
        ('deadband', 'Deadband (Change Tolerance)'),
    ], string="History Recording Strategy", default='on_change')
    deadband_value = fields.Float(string="Deadband Threshold", default=0.5)

    poll_interval = fields.Float(string="Poll Interval (seconds)", default=0.0, help="Set to 0 to inherit the connection default")
    retention_days = fields.Integer(string="History Retention (Days)", default=30)

    # PLC write security controls (IEC 62443 / FR-A3)
    is_writable = fields.Boolean(string="Allow PLC Write", default=False, tracking=True)
    min_write_value = fields.Float(string="Min Write Value", default=0.0)
    max_write_value = fields.Float(string="Max Write Value", default=100.0)
    require_two_step_approval = fields.Boolean(string="Require Two-Step Approval (Critical)", default=False)

    # Last value cache (FR-S1)
    last_value = fields.Char(string="Last Value", compute='_compute_last_reading', store=False)
    last_quality = fields.Selection([
        ('good', 'Good'),
        ('bad', 'Bad'),
        ('uncertain', 'Uncertain'),
    ], string="Quality", compute='_compute_last_reading', store=False)
    last_updated = fields.Datetime(string="Last Updated", compute='_compute_last_reading', store=False)

    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)

    value_ids = fields.One2many('scada.tag.value', 'tag_id', string="Value History")

    _sql_constraints = [
        ('code_unique', 'unique(code, company_id)', 'Tag code must be unique per company!'),
    ]

    @api.depends('name', 'code', 'connection_id')
    def _compute_display_name(self):
        """Build a human-readable display name including code and connection."""
        for rec in self:
            conn_name = rec.connection_id.name if rec.connection_id else '-'
            rec.display_name = f"[{rec.code}] {rec.name} ({conn_name})"

    def _compute_last_reading(self):
        """Populate last value, quality, and timestamp from scada.tag.last cache."""
        for rec in self:
            last = self.env['scada.tag.last'].search([('tag_id', '=', rec.id)], limit=1)
            rec.last_value = last.value_str if last else '-'
            rec.last_quality = last.quality if last else 'uncertain'
            rec.last_updated = last.timestamp if last else False

    def action_read_now(self):
        """FR-T8: Read the current value directly from the driver for debugging purposes."""
        self.ensure_one()
        driver_cls = ScadaDriverRegistry.get(self.connection_id.protocol)
        if not driver_cls:
            raise UserError(_("Driver for protocol '%s' is not available.") % self.connection_id.protocol)

        driver = driver_cls()
        driver.connect()
        readings = driver.read([self])
        reading = readings.get(self.code)

        if reading:
            # Apply value transformation
            val = reading.value
            if isinstance(val, (int, float)):
                val = (val * self.scale) + self.offset
                if self.formula:
                    try:
                        val = safe_eval(self.formula, {'value': val})
                    except Exception as e:
                        _logger.warning("Formula eval failed for tag %s: %s", self.code, e)

            # Update scada.tag.last cache
            last_model = self.env['scada.tag.last'].search([('tag_id', '=', self.id)], limit=1)
            vals = {
                'tag_id': self.id,
                'value_str': str(val),
                'value_num': float(val) if isinstance(val, (int, float)) else 0.0,
                'quality': reading.quality,
                'timestamp': reading.timestamp,
            }
            if last_model:
                last_model.write(vals)
            else:
                self.env['scada.tag.last'].create(vals)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Tag Read Successful"),
                    'message': _("Tag [%s] Value: %s %s (Quality: %s)") % (self.code, str(val), self.unit or '', reading.quality),
                    'type': 'info',
                    'sticky': False,
                }
            }


# =============================================================================
# 5. STORAGE & HISTORIAN (scada.tag.last, scada.tag.value, scada.tag.aggregate)
# =============================================================================
class ScadaTagLast(models.Model):
    _name = 'scada.tag.last'
    _description = 'PLC Tag Last Value'
    _rec_name = 'tag_id'

    tag_id = fields.Many2one('scada.tag', string="Tag", required=True, ondelete='cascade', index=True)
    value_str = fields.Char(string="Value (String)", required=True)
    value_num = fields.Float(string="Numeric Value", index=True)
    quality = fields.Selection([
        ('good', 'Good'),
        ('bad', 'Bad'),
        ('uncertain', 'Uncertain'),
    ], string="Quality", default='good', required=True)
    timestamp = fields.Datetime(string="Source Timestamp", required=True, default=fields.Datetime.now)

    _sql_constraints = [
        ('tag_id_unique', 'unique(tag_id)', 'Each tag can have only one last-value row!'),
    ]


class ScadaTagValue(models.Model):
    _name = 'scada.tag.value'
    _description = 'PLC Tag Value History (Append-Only Historian)'
    _order = 'timestamp desc, id desc'

    tag_id = fields.Many2one('scada.tag', string="Tag", required=True, ondelete='cascade', index=True)
    value_num = fields.Float(string="Numeric Value", index=True)
    value_str = fields.Char(string="Text Value")
    quality = fields.Selection([
        ('good', 'Good'),
        ('bad', 'Bad'),
        ('uncertain', 'Uncertain'),
    ], string="Quality", default='good', required=True)
    timestamp = fields.Datetime(string="Source Timestamp", required=True, index=True)
    received_at = fields.Datetime(string="Received at Odoo", default=fields.Datetime.now)


class ScadaTagAggregate(models.Model):
    _name = 'scada.tag.aggregate'
    _description = 'Tag Historian Aggregation (Hourly / Daily)'
    _order = 'bucket_start desc'

    tag_id = fields.Many2one('scada.tag', string="Tag", required=True, ondelete='cascade', index=True)
    bucket_type = fields.Selection([
        ('hour', 'Hourly'),
        ('day', 'Daily'),
    ], string="Aggregation Type", required=True, default='hour')
    bucket_start = fields.Datetime(string="Period Start", required=True, index=True)
    avg_value = fields.Float(string="Average")
    min_value = fields.Float(string="Min Value")
    max_value = fields.Float(string="Max Value")
    count_records = fields.Integer(string="Sample Count")


# =============================================================================
# 6. RULE ENGINE & ALARMS (scada.rule, scada.action, scada.alarm)
# =============================================================================
class ScadaRule(models.Model):
    _name = 'scada.rule'
    _description = 'SCADA Evaluation Rule & Alarm'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Rule Name", required=True, tracking=True)
    tag_id = fields.Many2one('scada.tag', string="Trigger Tag", required=True, tracking=True)

    operator = fields.Selection([
        ('gt', '> (Greater Than)'),
        ('lt', '< (Less Than)'),
        ('gte', '>= (Greater Than or Equal)'),
        ('lte', '<= (Less Than or Equal)'),
        ('eq', '= (Equal To)'),
        ('neq', '!= (Not Equal To)'),
        ('range', 'Outside Normal Range'),
        ('no_data', 'No Data (Loss of Signal)'),
    ], string="Trigger Condition", default='gt', required=True, tracking=True)

    threshold_value = fields.Float(string="Threshold Value", default=80.0, tracking=True)
    threshold_max = fields.Float(string="Range Upper Bound", default=100.0)
    duration_seconds = fields.Integer(string="Minimum Duration (seconds)", default=0)
    hysteresis = fields.Float(string="Hysteresis (Anti-Fluctuation)", default=0.0)

    severity = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('danger', 'Critical / High'),
    ], string="Severity", default='warning', required=True, tracking=True)

    action_ids = fields.One2many('scada.action', 'rule_id', string="Automated Actions")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)

    def evaluate(self, current_value):
        """Evaluate whether the rule is triggered based on the current tag value."""
        self.ensure_one()
        triggered = False
        val = float(current_value) if isinstance(current_value, (int, float)) else 0.0

        if self.operator == 'gt':
            triggered = val > self.threshold_value
        elif self.operator == 'lt':
            triggered = val < self.threshold_value
        elif self.operator == 'gte':
            triggered = val >= self.threshold_value
        elif self.operator == 'lte':
            triggered = val <= self.threshold_value
        elif self.operator == 'eq':
            triggered = val == self.threshold_value
        elif self.operator == 'neq':
            triggered = val != self.threshold_value
        elif self.operator == 'range':
            triggered = val < self.threshold_value or val > self.threshold_max

        if triggered:
            self._trigger_rule(val)

    def _trigger_rule(self, val):
        """Create an alarm and execute all configured actions (debounce: skip if alarm already active)."""
        self.ensure_one()
        # Check for an existing active alarm to prevent duplicates (Debounce / Rate Limit FR-R5)
        existing_alarm = self.env['scada.alarm'].search([
            ('rule_id', '=', self.id),
            ('state', 'in', ['active', 'ack']),
        ], limit=1)

        if not existing_alarm:
            alarm = self.env['scada.alarm'].create({
                'name': f"ALARM: {self.name}",
                'rule_id': self.id,
                'tag_id': self.tag_id.id,
                'device_id': self.tag_id.device_id.id if self.tag_id.device_id else False,
                'severity': self.severity,
                'trigger_value': val,
                'state': 'active',
                'triggered_at': fields.Datetime.now(),
            })
            # Execute all configured chained actions (FR-A1 through FR-A8)
            for action in self.action_ids:
                action.execute_action(alarm)


class ScadaAction(models.Model):
    _name = 'scada.action'
    _description = 'SCADA Rule Chained Action'

    rule_id = fields.Many2one('scada.rule', string="Related Rule", ondelete='cascade', required=True)
    action_type = fields.Selection([
        ('maintenance', 'Create Maintenance Request'),
        ('notify', 'Send Chatter / Email Notification'),
        ('write_plc', 'Write Value to PLC Tag'),
        ('server_action', 'Call Odoo Server Action'),
    ], string="Action Type", default='maintenance', required=True)

    # Maintenance configuration
    maintenance_team_id = fields.Many2one('maintenance.team', string="Maintenance Team")
    maintenance_title = fields.Char(string="Work Request Title", default="SCADA Alert: Machine Inspection Required")

    # PLC write configuration
    target_tag_id = fields.Many2one('scada.tag', string="Target PLC Tag", domain="[('is_writable', '=', True)]")
    write_value = fields.Char(string="Value to Write", default="0")

    def execute_action(self, alarm):
        """Execute this action in the context of a triggered alarm."""
        self.ensure_one()
        if self.action_type == 'maintenance':
            # Prevent duplicate maintenance tickets (FR-A1)
            equip_id = alarm.device_id.equipment_id.id if (alarm.device_id and alarm.device_id.equipment_id) else False
            req_vals = {
                'name': f"[{alarm.severity.upper()}] {self.maintenance_title} ({alarm.tag_id.name})",
                'description': f"Triggered by SCADA automatic alarm: Value={alarm.trigger_value} at {alarm.triggered_at}",
                'equipment_id': equip_id,
            }
            if self.maintenance_team_id:
                req_vals['maintenance_team_id'] = self.maintenance_team_id.id
            try:
                if 'maintenance.request' in self.env:
                    self.env['maintenance.request'].create(req_vals)
            except Exception as e:
                _logger.error("Failed to create maintenance.request: %s", e)

        elif self.action_type == 'write_plc':
            if self.target_tag_id and self.target_tag_id.is_writable:
                self.env['scada.write.request'].create_write_command(
                    tag=self.target_tag_id,
                    value=self.write_value,
                    origin=f"Rule: {self.rule_id.name}"
                )


class ScadaAlarm(models.Model):
    _name = 'scada.alarm'
    _description = 'SCADA Machine Alarm Event'
    _order = 'triggered_at desc, id desc'

    name = fields.Char(string="Alarm Name", required=True)
    rule_id = fields.Many2one('scada.rule', string="Trigger Rule", ondelete='set null')
    tag_id = fields.Many2one('scada.tag', string="Related Tag", required=True)
    device_id = fields.Many2one('scada.device', string="Machine / Device")

    severity = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('danger', 'Critical / High'),
    ], string="Severity", default='warning')

    trigger_value = fields.Float(string="Trigger Value")
    state = fields.Selection([
        ('active', 'Active'),
        ('ack', 'Acknowledged'),
        ('cleared', 'Cleared'),
    ], string="Alarm State", default='active', required=True)

    triggered_at = fields.Datetime(string="Triggered At", default=fields.Datetime.now)
    ack_at = fields.Datetime(string="Acknowledged At")
    ack_by = fields.Many2one('res.users', string="Acknowledged By")
    cleared_at = fields.Datetime(string="Cleared At")

    def action_acknowledge(self):
        """Mark the alarm as acknowledged by the current user."""
        self.write({
            'state': 'ack',
            'ack_at': fields.Datetime.now(),
            'ack_by': self.env.user.id,
        })

    def action_clear(self):
        """Close the alarm once the machine condition has returned to normal."""
        self.write({
            'state': 'cleared',
            'cleared_at': fields.Datetime.now(),
        })


# =============================================================================
# 7. MAPPING TO ODOO MODELS (scada.mapping)
# =============================================================================
class ScadaMapping(models.Model):
    _name = 'scada.mapping'
    _description = 'SCADA Tag Mapping to Odoo Data (MRP/Field)'

    name = fields.Char(string="Mapping Name", required=True)
    tag_id = fields.Many2one('scada.tag', string="Source PLC Tag", required=True)
    target_model = fields.Char(string="Target Odoo Model", required=True, default="mrp.production")
    target_field = fields.Char(string="Target Field", required=True, default="qty_producing")

    mode = fields.Selection([
        ('set', 'Set Value Directly'),
        ('accumulate', 'Accumulate (Add)'),
        ('delta', 'Delta (Incremental)'),
    ], string="Update Mode", default='delta', required=True)

    condition_domain = fields.Char(string="Record Search Domain", default="[('state', '=', 'progress')]")
    active = fields.Boolean(default=True)


# =============================================================================
# 8. SAFE WRITE REQUESTS & IEC 62443 AUDIT LOGS
# =============================================================================
class ScadaWriteRequest(models.Model):
    _name = 'scada.write.request'
    _description = 'PLC Write Command Queue'
    _order = 'create_date desc'

    tag_id = fields.Many2one('scada.tag', string="Target Tag", required=True)
    requested_value = fields.Char(string="Requested Value", required=True)
    state = fields.Selection([
        ('pending', 'Pending Gateway Execution'),
        ('sent', 'Sent to Gateway'),
        ('success', 'Successfully Written to PLC'),
        ('rejected', 'Rejected (Value Bounds / Access Rights)'),
        ('failed', 'Failed / Timeout'),
    ], string="Write Status", default='pending')

    origin = fields.Char(string="Command Origin", default="Manual Engineer")
    executed_by = fields.Many2one('res.users', string="Executed By", default=lambda self: self.env.user)
    response_message = fields.Text(string="Gateway / PLC Response")

    @api.model
    def create_write_command(self, tag, value, origin="Manual"):
        """
        Safely create a PLC write command with IEC 62443 validation (FR-A3, Section 7.3).

        Checks performed (in order):
        1. Global read-only mode
        2. Tag writable flag
        3. Min/max value range bounds
        """
        readonly_mode = self.env['ir.config_parameter'].sudo().get_param('scada_plc_connector.plc_write_mode', 'enabled')
        if readonly_mode == 'readonly':
            raise UserError(_("OT Security Alert: The SCADA system is in GLOBAL READ-ONLY mode. PLC writes are disabled."))

        if not tag.is_writable:
            raise UserError(_("Tag '%s' does not have write permission (Read-Only).") % tag.name)

        # Validate numeric value bounds
        try:
            num_val = float(value)
            if num_val < tag.min_write_value or num_val > tag.max_write_value:
                raise ValidationError(_("Value %.2f is outside the allowed safe range (Min: %.2f, Max: %.2f).") % (num_val, tag.min_write_value, tag.max_write_value))
        except ValueError:
            pass

        req = self.create({
            'tag_id': tag.id,
            'requested_value': str(value),
            'origin': origin,
            'state': 'pending',
        })

        # Record append-only audit log
        self.env['scada.log'].create({
            'log_type': 'write_audit',
            'level': 'info',
            'message': f"Write command created for Tag [{tag.code}] = {value} by user {self.env.user.name}. Origin: {origin}",
            'connection_id': tag.connection_id.id,
        })
        return req


class ScadaLog(models.Model):
    _name = 'scada.log'
    _description = 'SCADA Operational Audit & Log (IEC 62443)'
    _order = 'timestamp desc, id desc'

    log_type = fields.Selection([
        ('connection', 'PLC Connection'),
        ('telemetry', 'Telemetry / Ingest'),
        ('write_audit', 'PLC Write Audit (IEC 62443)'),
        ('security', 'Security & Authentication'),
    ], string="Log Category", required=True, default='connection')

    level = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string="Level", default='info', required=True)

    message = fields.Text(string="Log Message", required=True)
    gateway_id = fields.Many2one('scada.gateway', string="Gateway")
    connection_id = fields.Many2one('scada.connection', string="Connection")
    timestamp = fields.Datetime(string="Timestamp", default=fields.Datetime.now, required=True)
