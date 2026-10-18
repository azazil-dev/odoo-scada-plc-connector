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

    name = fields.Char(string="Nama Gateway", required=True, tracking=True)
    code = fields.Char(string="Kode Unik", required=True, copy=False, default=lambda self: 'GW-' + secrets.token_hex(4).upper())
    mode = fields.Selection([
        ('gateway', 'Remote Edge Gateway (REST/JSON Service)'),
        ('embedded', 'Embedded Odoo Worker (Local Driver Polling)'),
    ], string="Mode Operasi", default='gateway', required=True, tracking=True)
    
    status = fields.Selection([
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('warning', 'Degraded / Warning'),
    ], string="Status Gateway", default='offline', compute='_compute_status', store=True, tracking=True)

    api_key_hash = fields.Char(string="API Key Hash", copy=False, readonly=True)
    api_key_display = fields.Char(string="API Key (Salin Sekarang)", copy=False, readonly=True,
                                  help="Kunci otentikasi rahasia untuk Gateway. Hanya ditampilkan sekali saat dibuat.")
    
    last_heartbeat = fields.Datetime(string="Heartbeat Terakhir", readonly=True)
    version = fields.Char(string="Versi Gateway", readonly=True)
    host_os = fields.Char(string="Sistem Operasi / Host", readonly=True)
    active_tags_count = fields.Integer(string="Tag Aktif", compute='_compute_tag_stats')
    buffer_queue_size = fields.Integer(string="Buffer Store-and-Forward", default=0, readonly=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Perusahaan", default=lambda self: self.env.company)

    connection_ids = fields.One2many('scada.connection', 'gateway_id', string="Koneksi Terhubung")
    log_ids = fields.One2many('scada.log', 'gateway_id', string="Log Gateway")

    @api.depends('last_heartbeat')
    def _compute_status(self):
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
        for rec in self:
            tags = self.env['scada.tag'].search_count([
                ('connection_id.gateway_id', '=', rec.id),
                ('active', '=', True)
            ])
            rec.active_tags_count = tags

    def action_generate_api_key(self):
        """Menghasilkan API Key baru dan menyimpannya dalam bentuk SHA-256 hash."""
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
            'message': f"API Key di-generate ulang untuk gateway '{self.name}'.",
            'gateway_id': self.id,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('API Key Berhasil Dibuat'),
                'message': _('Harap segera salin API Key: %s. Nilai ini tidak akan disimpan dalam teks mentah.') % raw_key,
                'type': 'warning',
                'sticky': True,
            }
        }


# =============================================================================
# 2. PLC CONNECTION (scada.connection)
# =============================================================================
class ScadaConnection(models.Model):
    _name = 'scada.connection'
    _description = 'Koneksi PLC / SCADA'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Nama Koneksi", required=True, tracking=True)
    code = fields.Char(string="Kode Unik", required=True, copy=False, default=lambda self: 'CONN-' + secrets.token_hex(3).upper())
    gateway_id = fields.Many2one('scada.gateway', string="Gateway Penanggung Jawab", required=True, tracking=True)
    
    protocol = fields.Selection([
        ('simulator', 'Built-in PLC Simulator'),
        ('modbus_tcp', 'Modbus TCP / Ethernet'),
        ('opcua', 'OPC UA'),
        ('s7', 'Siemens S7 (Profinet)'),
        ('mqtt', 'MQTT / Sparkplug B'),
    ], string="Protokol Industri", default='simulator', required=True, tracking=True)

    host = fields.Char(string="Host / IP Address / Broker", default="127.0.0.1", required=True)
    port = fields.Integer(string="Port", default=502, required=True)
    timeout = fields.Float(string="Timeout (detik)", default=3.0)
    retry_count = fields.Integer(string="Maksimum Retry", default=3)
    poll_interval_default = fields.Float(string="Interval Polling Default (detik)", default=1.0)
    
    # Parameter Tambahan berbasis Protokol (Disimpan dalam JSON terenkripsi/aman)
    protocol_params = fields.Text(string="Parameter Khusus (JSON)", default="{}")
    unit_id = fields.Integer(string="Modbus Slave/Unit ID", default=1)
    s7_rack = fields.Integer(string="S7 Rack", default=0)
    s7_slot = fields.Integer(string="S7 Slot", default=1)
    mqtt_topic_prefix = fields.Char(string="MQTT Topic Prefix", default="factory/line1")

    state = fields.Selection([
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('error', 'Error'),
    ], string="Status Koneksi", default='offline', tracking=True)

    last_seen = fields.Datetime(string="Terakhir Aktif", readonly=True)
    latency_ms = fields.Float(string="Latensi (ms)", default=0.0, readonly=True)
    error_count = fields.Integer(string="Total Error", default=0, readonly=True)
    last_error_message = fields.Text(string="Pesan Error Terakhir", readonly=True)
    
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Perusahaan", default=lambda self: self.env.company)

    device_ids = fields.One2many('scada.device', 'connection_id', string="Perangkat / Mesin")
    tag_ids = fields.One2many('scada.tag', 'connection_id', string="Daftar Tag")

    def action_test_connection(self):
        """FR-C3: Menjalankan tes koneksi langsung lewat driver (baik lokal maupun via driver registry)."""
        self.ensure_one()
        driver_cls = ScadaDriverRegistry.get(self.protocol)
        if not driver_cls:
            raise UserError(_("Driver untuk protokol '%s' tidak ditemukan.") % self.protocol)

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
                    'message': f"Tes koneksi '{self.name}' BERHASIL: {msg} ({elapsed_ms:.1f} ms)",
                    'connection_id': self.id,
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Koneksi Berhasil!'),
                        'message': _("%s (Latensi: %.1f ms)") % (msg, elapsed_ms),
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
                        'title': _('Koneksi Gagal'),
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
                    'title': _('Error Tes Koneksi'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }


# =============================================================================
# 3. DEVICE / MESIN (scada.device)
# =============================================================================
class ScadaDevice(models.Model):
    _name = 'scada.device'
    _description = 'Perangkat / Mesin Pabrik'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Nama Perangkat / Mesin", required=True, tracking=True)
    code = fields.Char(string="Nomor Aset / Kode", required=True, copy=False)
    connection_id = fields.Many2one('scada.connection', string="Koneksi Utama", required=True, tracking=True)
    description = fields.Text(string="Deskripsi / Lokasi")

    # Integrasi ke Work Center & Maintenance Equipment (FR-D2)
    workcenter_id = fields.Many2one('mrp.workcenter', string="Work Center Terkait (MRP)", tracking=True)
    equipment_id = fields.Many2one('maintenance.equipment', string="Equipment Terkait (Maintenance)", tracking=True)

    state = fields.Selection([
        ('running', 'Running / Beroperasi'),
        ('idle', 'Idle / Menunggu'),
        ('stopped', 'Stopped / Berhenti'),
        ('fault', 'Fault / Gangguan Mesin'),
    ], string="Status Mesin", default='running', tracking=True)

    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Perusahaan", default=lambda self: self.env.company)

    tag_ids = fields.One2many('scada.tag', 'device_id', string="Daftar Tag Mesin")
    alarm_ids = fields.One2many('scada.alarm', 'device_id', string="Alarm Aktif")


# =============================================================================
# 4. TAG MANAGEMENT (scada.tag)
# =============================================================================
class ScadaTag(models.Model):
    _name = 'scada.tag'
    _description = 'Definisi Tag PLC / SCADA'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'display_name'

    name = fields.Char(string="Nama Tag", required=True, tracking=True)
    code = fields.Char(string="Kode Tag Unik", required=True, copy=False, tracking=True)
    display_name = fields.Char(string="Nama Tampilan", compute='_compute_display_name', store=True)
    
    connection_id = fields.Many2one('scada.connection', string="Koneksi", required=True, ondelete='cascade')
    device_id = fields.Many2one('scada.device', string="Perangkat / Mesin Terkait", ondelete='set null')
    
    address = fields.Char(string="Alamat Register / Topik", required=True, help="Contoh: 40001, DB1.DBD0, SIM:TEMP_01, ns=2;s=Temperature")
    data_type = fields.Selection([
        ('bool', 'Boolean (Bit / Coil)'),
        ('int16', 'Integer 16-Bit'),
        ('int32', 'Integer 32-Bit'),
        ('uint16', 'Unsigned Integer 16-Bit'),
        ('uint32', 'Unsigned Integer 32-Bit'),
        ('float32', 'Float 32-Bit (IEEE 754)'),
        ('float64', 'Double 64-Bit'),
        ('string', 'String / Karakter ASCII'),
    ], string="Tipe Data", default='float32', required=True)

    mode = fields.Selection([
        ('read', 'Read-Only (Hanya Baca)'),
        ('write', 'Write-Only (Hanya Tulis)'),
        ('read_write', 'Read / Write (Baca & Tulis)'),
    ], string="Mode Akses", default='read', required=True)

    unit = fields.Char(string="Satuan Unit", help="Contoh: °C, bar, RPM, pcs, A, V, kW")
    description = fields.Text(string="Keterangan")

    # Transformasi Nilai (FR-T2)
    scale = fields.Float(string="Scale (Faktor Pengali)", default=1.0)
    offset = fields.Float(string="Offset (Pelecut)", default=0.0)
    formula = fields.Char(string="Formula Kustom", help="Ekspresi safe_eval. Contoh: value * 0.1 - 5.0")

    # Strategi Perekaman (FR-T3)
    record_strategy = fields.Selection([
        ('periodic', 'Periodik Sesuai Interval'),
        ('on_change', 'On-Change (Hanya Bila Berubah)'),
        ('deadband', 'Deadband Toleransi Perubahan'),
    ], string="Strategi Simpan Histori", default='on_change')
    deadband_value = fields.Float(string="Batas Deadband", default=0.5)

    poll_interval = fields.Float(string="Interval Polling (detik)", default=0.0, help="Isi 0 untuk mengikuti default koneksi")
    retention_days = fields.Integer(string="Retensi Histori (Hari)", default=30)

    # Kontrol Keamanan Tulis PLC (IEC 62443 / FR-A3)
    is_writable = fields.Boolean(string="Izinkan Penulisan ke PLC", default=False, tracking=True)
    min_write_value = fields.Float(string="Nilai Tulis Minimum", default=0.0)
    max_write_value = fields.Float(string="Nilai Tulis Maksimum", default=100.0)
    require_two_step_approval = fields.Boolean(string="Wajib Persetujuan 2 Langkah (Kritis)", default=False)

    # Cache Nilai Terakhir (FR-S1)
    last_value = fields.Char(string="Nilai Terakhir", compute='_compute_last_reading', store=False)
    last_quality = fields.Selection([
        ('good', 'Good (Valid)'),
        ('bad', 'Bad (Invalid / Error)'),
        ('uncertain', 'Uncertain'),
    ], string="Kualitas", compute='_compute_last_reading', store=False)
    last_updated = fields.Datetime(string="Waktu Pembaruan", compute='_compute_last_reading', store=False)

    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Perusahaan", default=lambda self: self.env.company)

    value_ids = fields.One2many('scada.tag.value', 'tag_id', string="Histori Nilai")

    _sql_constraints = [
        ('code_unique', 'unique(code, company_id)', 'Kode Tag harus unik per perusahaan!'),
    ]

    @api.depends('name', 'code', 'connection_id')
    def _compute_display_name(self):
        for rec in self:
            conn_name = rec.connection_id.name if rec.connection_id else '-'
            rec.display_name = f"[{rec.code}] {rec.name} ({conn_name})"

    def _compute_last_reading(self):
        for rec in self:
            last = self.env['scada.tag.last'].search([('tag_id', '=', rec.id)], limit=1)
            rec.last_value = last.value_str if last else '-'
            rec.last_quality = last.quality if last else 'uncertain'
            rec.last_updated = last.timestamp if last else False

    def action_read_now(self):
        """FR-T8: Baca nilai langsung dari simulator / driver untuk debugging."""
        self.ensure_one()
        driver_cls = ScadaDriverRegistry.get(self.connection_id.protocol)
        if not driver_cls:
            raise UserError(_("Driver untuk protokol '%s' tidak tersedia.") % self.connection_id.protocol)

        driver = driver_cls()
        driver.connect()
        readings = driver.read([self])
        reading = readings.get(self.code)
        
        if reading:
            # Terapkan transformasi nilai
            val = reading.value
            if isinstance(val, (int, float)):
                val = (val * self.scale) + self.offset
                if self.formula:
                    try:
                        val = safe_eval(self.formula, {'value': val})
                    except Exception as e:
                        _logger.warning("Formula eval failed for tag %s: %s", self.code, e)

            # Update ke scada.tag.last
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
                    'title': _("Pembacaan Tag Berhasil"),
                    'message': _("Tag [%s] Nilai: %s %s (Kualitas: %s)") % (self.code, str(val), self.unit or '', reading.quality),
                    'type': 'info',
                    'sticky': False,
                }
            }


# =============================================================================
# 5. STORAGE & HISTORIAN (scada.tag.last, scada.tag.value, scada.tag.aggregate)
# =============================================================================
class ScadaTagLast(models.Model):
    _name = 'scada.tag.last'
    _description = 'Nilai Terakhir Tag PLC'
    _rec_name = 'tag_id'

    tag_id = fields.Many2one('scada.tag', string="Tag", required=True, ondelete='cascade', index=True)
    value_str = fields.Char(string="Nilai (String)", required=True)
    value_num = fields.Float(string="Nilai Numerik", index=True)
    quality = fields.Selection([
        ('good', 'Good'),
        ('bad', 'Bad'),
        ('uncertain', 'Uncertain'),
    ], string="Kualitas", default='good', required=True)
    timestamp = fields.Datetime(string="Timestamp Sumber", required=True, default=fields.Datetime.now)

    _sql_constraints = [
        ('tag_id_unique', 'unique(tag_id)', 'Setiap tag hanya memiliki satu baris nilai terakhir!'),
    ]


class ScadaTagValue(models.Model):
    _name = 'scada.tag.value'
    _description = 'Histori Nilai Tag PLC (Append-Only Historian)'
    _order = 'timestamp desc, id desc'

    tag_id = fields.Many2one('scada.tag', string="Tag", required=True, ondelete='cascade', index=True)
    value_num = fields.Float(string="Nilai Numerik", index=True)
    value_str = fields.Char(string="Nilai Teks")
    quality = fields.Selection([
        ('good', 'Good'),
        ('bad', 'Bad'),
        ('uncertain', 'Uncertain'),
    ], string="Kualitas", default='good', required=True)
    timestamp = fields.Datetime(string="Timestamp Sumber", required=True, index=True)
    received_at = fields.Datetime(string="Timestamp Terima di Odoo", default=fields.Datetime.now)


class ScadaTagAggregate(models.Model):
    _name = 'scada.tag.aggregate'
    _description = 'Agregasi Historian Tag (Per Jam / Harian)'
    _order = 'bucket_start desc'

    tag_id = fields.Many2one('scada.tag', string="Tag", required=True, ondelete='cascade', index=True)
    bucket_type = fields.Selection([
        ('hour', 'Per Jam'),
        ('day', 'Per Hari'),
    ], string="Tipe Agregasi", required=True, default='hour')
    bucket_start = fields.Datetime(string="Awal Periode", required=True, index=True)
    avg_value = fields.Float(string="Rata-rata")
    min_value = fields.Float(string="Nilai Minimum")
    max_value = fields.Float(string="Nilai Maksimum")
    count_records = fields.Integer(string="Jumlah Sampel")


# =============================================================================
# 6. RULE ENGINE & ALARMS (scada.rule, scada.action, scada.alarm)
# =============================================================================
class ScadaRule(models.Model):
    _name = 'scada.rule'
    _description = 'Aturan Evaluasi & Alarm SCADA'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Nama Aturan", required=True, tracking=True)
    tag_id = fields.Many2one('scada.tag', string="Tag Pemicu", required=True, tracking=True)
    
    operator = fields.Selection([
        ('gt', '> (Lebih Besar Dari)'),
        ('lt', '< (Lebih Kecil Dari)'),
        ('gte', '>= (Lebih Besar Sama Dengan)'),
        ('lte', '<= (Lebih Kecil Sama Dengan)'),
        ('eq', '= (Sama Dengan)'),
        ('neq', '!= (Tidak Sama Dengan)'),
        ('range', 'Di Luar Rentang Normal'),
        ('no_data', 'Tidak Ada Data (Loss of Signal)'),
    ], string="Kondisi Pemicu", default='gt', required=True, tracking=True)

    threshold_value = fields.Float(string="Nilai Ambang Batas", default=80.0, tracking=True)
    threshold_max = fields.Float(string="Batas Atas Rentang", default=100.0)
    duration_seconds = fields.Integer(string="Durasi Minimum Terpenuhi (detik)", default=0)
    hysteresis = fields.Float(string="Histeresis (Pencegah Fluktuasi)", default=0.0)
    
    severity = fields.Selection([
        ('info', 'Informasi (Info)'),
        ('warning', 'Peringatan (Warning)'),
        ('danger', 'Kritis / Bahaya (High/Critical)'),
    ], string="Tingkat Keparahan (Severity)", default='warning', required=True, tracking=True)

    action_ids = fields.One2many('scada.action', 'rule_id', string="Aksi Otomatis")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Perusahaan", default=lambda self: self.env.company)

    def evaluate(self, current_value):
        """Mengevaluasi apakah aturan terpicu berdasarkan nilai saat ini."""
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
        self.ensure_one()
        # Cek apakah ada alarm aktif yang belum di-clear untuk mencegah duplikasi (Debounce / Rate Limit FR-R5)
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
            # Eksekusi aksi yang terkonfigurasi (FR-A1 s/d FR-A8)
            for action in self.action_ids:
                action.execute_action(alarm)


class ScadaAction(models.Model):
    _name = 'scada.action'
    _description = 'Aksi Terangkai Rule SCADA'

    rule_id = fields.Many2one('scada.rule', string="Rule Terkait", ondelete='cascade', required=True)
    action_type = fields.Selection([
        ('maintenance', 'Buat Maintenance Request (Perawatan)'),
        ('notify', 'Kirim Notifikasi Chatter / Email'),
        ('write_plc', 'Tulis Nilai ke Tag PLC'),
        ('server_action', 'Panggil Odoo Server Action'),
    ], string="Tipe Aksi", default='maintenance', required=True)

    # Konfigurasi Maintenance
    maintenance_team_id = fields.Many2one('maintenance.team', string="Tim Maintenance")
    maintenance_title = fields.Char(string="Judul Work Request", default="Peringatan SCADA: Perlu Pengecekan Mesin")

    # Konfigurasi Penulisan PLC
    target_tag_id = fields.Many2one('scada.tag', string="Target Tag PLC", domain="[('is_writable', '=', True)]")
    write_value = fields.Char(string="Nilai Dituliskan", default="0")

    def execute_action(self, alarm):
        self.ensure_one()
        if self.action_type == 'maintenance':
            # Pencegahan duplikasi tiket maintenance (FR-A1)
            equip_id = alarm.device_id.equipment_id.id if (alarm.device_id and alarm.device_id.equipment_id) else False
            req_vals = {
                'name': f"[{alarm.severity.upper()}] {self.maintenance_title} ({alarm.tag_id.name})",
                'description': f"Terpicu oleh alarm otomatis SCADA: Nilai={alarm.trigger_value} pada {alarm.triggered_at}",
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
    _description = 'Kejadian Alarm Mesin SCADA'
    _order = 'triggered_at desc, id desc'

    name = fields.Char(string="Nama Alarm", required=True)
    rule_id = fields.Many2one('scada.rule', string="Rule Pemicu", ondelete='set null')
    tag_id = fields.Many2one('scada.tag', string="Tag Terkait", required=True)
    device_id = fields.Many2one('scada.device', string="Mesin / Perangkat")
    
    severity = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('danger', 'Critical / High'),
    ], string="Tingkat", default='warning')

    trigger_value = fields.Float(string="Nilai Saat Terpicu")
    state = fields.Selection([
        ('active', 'Aktif (Active)'),
        ('ack', 'Diakui (Acknowledged)'),
        ('cleared', 'Selesai (Cleared)'),
    ], string="Status Alarm", default='active', required=True)

    triggered_at = fields.Datetime(string="Waktu Terpicu", default=fields.Datetime.now)
    ack_at = fields.Datetime(string="Waktu Diakui")
    ack_by = fields.Many2one('res.users', string="Diakui Oleh")
    cleared_at = fields.Datetime(string="Waktu Clear")

    def action_acknowledge(self):
        """User mengakui alarm telah dilihat dan sedang ditangani."""
        self.write({
            'state': 'ack',
            'ack_at': fields.Datetime.now(),
            'ack_by': self.env.user.id,
        })

    def action_clear(self):
        """Mengakhiri alarm saat kondisi mesin telah normal."""
        self.write({
            'state': 'cleared',
            'cleared_at': fields.Datetime.now(),
        })


# =============================================================================
# 7. MAPPING TO ODOO MODELS (scada.mapping)
# =============================================================================
class ScadaMapping(models.Model):
    _name = 'scada.mapping'
    _description = 'Pemetaan Tag SCADA ke Data Odoo (MRP/Field)'

    name = fields.Char(string="Nama Pemetaan", required=True)
    tag_id = fields.Many2one('scada.tag', string="Sumber Tag PLC", required=True)
    target_model = fields.Char(string="Model Target Odoo", required=True, default="mrp.production")
    target_field = fields.Char(string="Field Target", required=True, default="qty_producing")
    
    mode = fields.Selection([
        ('set', 'Set Nilai Langsung'),
        ('accumulate', 'Akumulasi (Tambah)'),
        ('delta', 'Delta (Pertambahan Nilai)'),
    ], string="Mode Pembaruan", default='delta', required=True)

    condition_domain = fields.Char(string="Domain Pencarian Record", default="[('state', '=', 'progress')]")
    active = fields.Boolean(default=True)


# =============================================================================
# 8. SAFE WRITE REQUESTS & IEC 62443 AUDIT LOGS
# =============================================================================
class ScadaWriteRequest(models.Model):
    _name = 'scada.write.request'
    _description = 'Antrean Perintah Tulis ke PLC'
    _order = 'create_date desc'

    tag_id = fields.Many2one('scada.tag', string="Target Tag", required=True)
    requested_value = fields.Char(string="Nilai yang Diminta", required=True)
    state = fields.Selection([
        ('pending', 'Menunggu Eksekusi Gateway'),
        ('sent', 'Terkirim ke Gateway'),
        ('success', 'Berhasil Ditulis ke PLC'),
        ('rejected', 'Ditolak (Batas Nilai / Hak Akses)'),
        ('failed', 'Gagal / Timeout'),
    ], string="Status Tulis", default='pending', tracking=True)

    origin = fields.Char(string="Sumber Perintah", default="Manual Engineer")
    executed_by = fields.Many2one('res.users', string="Dieksekusi Oleh", default=lambda self: self.env.user)
    response_message = fields.Text(string="Respon Gateway / PLC")
    
    @api.model
    def create_write_command(self, tag, value, origin="Manual"):
        """
        Metode aman membuat perintah tulis dengan validasi IEC 62443 (FR-A3, Section 7.3):
        1. Cek mode read-only global
        2. Cek apakah tag bertanda writable
        3. Cek batas rentang minimum/maksimum
        """
        readonly_mode = self.env['ir.config_parameter'].sudo().get_param('scada.readonly_mode', False)
        if readonly_mode:
            raise UserError(_("Peringatan Keamanan OT: Sistem SCADA sedang dalam mode READ-ONLY GLOBAL. Penulisan ke PLC dinonaktifkan."))

        if not tag.is_writable:
            raise UserError(_("Tag '%s' tidak memiliki izin penulisan (Read-Only).") % tag.name)

        # Validasi batas nilai numerik
        try:
            num_val = float(value)
            if num_val < tag.min_write_value or num_val > tag.max_write_value:
                raise ValidationError(_("Nilai %.2f berada di luar batas aman yang diizinkan (Min: %.2f, Max: %.2f).") % (num_val, tag.min_write_value, tag.max_write_value))
        except ValueError:
            pass

        req = self.create({
            'tag_id': tag.id,
            'requested_value': str(value),
            'origin': origin,
            'state': 'pending',
        })

        # Catat audit log tak dapat diubah (append-only)
        self.env['scada.log'].create({
            'log_type': 'write_audit',
            'level': 'info',
            'message': f"Perintah tulis dibuat untuk Tag [{tag.code}] = {value} oleh user {self.env.user.name}. Asal: {origin}",
            'connection_id': tag.connection_id.id,
        })
        return req


class ScadaLog(models.Model):
    _name = 'scada.log'
    _description = 'Audit & Log Operasional SCADA (IEC 62443)'
    _order = 'timestamp desc, id desc'

    log_type = fields.Selection([
        ('connection', 'Koneksi PLC'),
        ('telemetry', 'Telemetri / Ingest'),
        ('write_audit', 'Audit Tulis PLC (IEC 62443)'),
        ('security', 'Keamanan & Autentikasi'),
    ], string="Kategori Log", required=True, default='connection')

    level = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string="Tingkat", default='info', required=True)

    message = fields.Text(string="Pesan Log", required=True)
    gateway_id = fields.Many2one('scada.gateway', string="Gateway")
    connection_id = fields.Many2one('scada.connection', string="Koneksi")
    timestamp = fields.Datetime(string="Waktu", default=fields.Datetime.now, required=True)
