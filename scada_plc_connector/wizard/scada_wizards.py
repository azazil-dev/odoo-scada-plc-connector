# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import csv
import base64
import io

class ScadaTagImportWizard(models.TransientModel):
    _name = 'scada.tag.import.wizard'
    _description = 'Wizard Import Tag PLC dari CSV'

    connection_id = fields.Many2one('scada.connection', string="Target Koneksi PLC", required=True)
    device_id = fields.Many2one('scada.device', string="Target Mesin (Opsional)")
    file_data = fields.Binary(string="File CSV Tag", required=True)
    filename = fields.Char(string="Nama File")

    def action_import(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Pilih file CSV yang akan diimpor."))

        decoded = base64.b64decode(self.file_data)
        reader = csv.DictReader(io.StringIO(decoded.decode('utf-8', errors='ignore')))
        
        count = 0
        tag_obj = self.env['scada.tag']
        for row in reader:
            code = row.get('code') or row.get('Code') or row.get('tag_code')
            name = row.get('name') or row.get('Name') or code
            address = row.get('address') or row.get('Address') or row.get('register')
            dtype = row.get('data_type', 'float32')
            unit = row.get('unit', '')

            if not code or not address:
                continue

            existing = tag_obj.search([
                ('code', '=', code),
                ('connection_id', '=', self.connection_id.id)
            ], limit=1)

            vals = {
                'name': name,
                'code': code,
                'connection_id': self.connection_id.id,
                'device_id': self.device_id.id if self.device_id else False,
                'address': address,
                'data_type': dtype,
                'unit': unit,
            }
            if existing:
                existing.write(vals)
            else:
                tag_obj.create(vals)
            count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Import Tag Selesai"),
                'message': _("Berhasil mengimpor %d tag ke koneksi '%s'.") % (count, self.connection_id.name),
                'type': 'success',
                'sticky': False,
            }
        }


class ScadaTagWriteWizard(models.TransientModel):
    _name = 'scada.tag.write.wizard'
    _description = 'Wizard Penulisan Nilai ke Register Tag PLC'

    tag_id = fields.Many2one('scada.tag', string="Target Tag", required=True)
    current_value = fields.Char(string="Nilai Saat Ini", readonly=True)
    new_value = fields.Char(string="Nilai Baru yang Ditulis", required=True)
    unit = fields.Char(string="Satuan", readonly=True)
    min_value = fields.Float(string="Batas Minimum", readonly=True)
    max_value = fields.Float(string="Batas Maksimum", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id:
            tag = self.env['scada.tag'].browse(active_id)
            res.update({
                'tag_id': tag.id,
                'current_value': tag.last_value,
                'unit': tag.unit,
                'min_value': tag.min_write_value,
                'max_value': tag.max_write_value,
            })
        return res

    def action_execute_write(self):
        self.ensure_one()
        req = self.env['scada.write.request'].create_write_command(
            tag=self.tag_id,
            value=self.new_value,
            origin=f"Manual Operator oleh {self.env.user.name}"
        )
        # Jika koneksi adalah simulator bawaan, eksekusi tulis seketika!
        if self.tag_id.connection_id.protocol == 'simulator':
            driver_cls = ScadaDriverRegistry.get('simulator')
            driver = driver_cls()
            driver.write(self.tag_id, self.new_value)
            req.write({'state': 'success', 'response_message': 'Simulator register updated'})
            # Update scada.tag.last
            last = self.env['scada.tag.last'].search([('tag_id', '=', self.tag_id.id)], limit=1)
            if last:
                last.write({'value_str': str(self.new_value), 'timestamp': fields.Datetime.now()})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Perintah Tulis Terkirim"),
                'message': _("Perintah tulis ke tag [%s] = %s berhasil didaftarkan.") % (self.tag_id.code, self.new_value),
                'type': 'success',
                'sticky': False,
            }
        }

