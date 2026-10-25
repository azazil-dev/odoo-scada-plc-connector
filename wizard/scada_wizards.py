# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import csv
import base64
import io

class ScadaTagImportWizard(models.TransientModel):
    _name = 'scada.tag.import.wizard'
    _description = 'PLC Tag CSV Import Wizard'

    connection_id = fields.Many2one('scada.connection', string="Target PLC Connection", required=True)
    device_id = fields.Many2one('scada.device', string="Target Machine (Optional)")
    file_data = fields.Binary(string="Tag CSV File", required=True)
    filename = fields.Char(string="File Name")

    def action_import(self):
        """Parse the uploaded CSV and create or update scada.tag records."""
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Please select a CSV file to import."))

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
                'title': _("Tag Import Complete"),
                'message': _("Successfully imported %d tags to connection '%s'.") % (count, self.connection_id.name),
                'type': 'success',
                'sticky': False,
            }
        }


class ScadaTagWriteWizard(models.TransientModel):
    _name = 'scada.tag.write.wizard'
    _description = 'PLC Tag Register Write Wizard'

    tag_id = fields.Many2one('scada.tag', string="Target Tag", required=True)
    current_value = fields.Char(string="Current Value", readonly=True)
    new_value = fields.Char(string="New Value to Write", required=True)
    unit = fields.Char(string="Unit", readonly=True)
    min_value = fields.Float(string="Min Value", readonly=True)
    max_value = fields.Float(string="Max Value", readonly=True)

    @api.model
    def default_get(self, fields_list):
        """Pre-populate wizard fields from the active tag record."""
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
        """Validate and submit the write command; execute immediately for simulator connections."""
        self.ensure_one()
        req = self.env['scada.write.request'].create_write_command(
            tag=self.tag_id,
            value=self.new_value,
            origin=f"Manual by Operator {self.env.user.name}"
        )
        # For the built-in simulator, execute the write immediately
        if self.tag_id.connection_id.protocol == 'simulator':
            from odoo.addons.scada_plc_connector.models.scada_drivers import ScadaDriverRegistry
            driver_cls = ScadaDriverRegistry.get('simulator')
            driver = driver_cls()
            driver.write(self.tag_id, self.new_value)
            req.write({'state': 'success', 'response_message': 'Simulator register updated'})
            # Refresh scada.tag.last cache
            last = self.env['scada.tag.last'].search([('tag_id', '=', self.tag_id.id)], limit=1)
            if last:
                last.write({'value_str': str(self.new_value), 'timestamp': fields.Datetime.now()})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Write Command Submitted"),
                'message': _("Write command for tag [%s] = %s has been registered.") % (self.tag_id.code, self.new_value),
                'type': 'success',
                'sticky': False,
            }
        }
