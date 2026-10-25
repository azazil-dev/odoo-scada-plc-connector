# -*- coding: utf-8 -*-
"""
REST API Endpoints for Edge Gateway (PRD Section 5.3):
- POST /scada/api/v1/ingest         : Receive a batch of tag readings from the Gateway
- GET  /scada/api/v1/config         : Retrieve active connection & tag configuration (with ETag)
- POST /scada/api/v1/heartbeat      : Gateway heartbeat & status update
- POST /scada/api/v1/commands       : Fetch pending write command queue
- POST /scada/api/v1/commands/:id/result : Confirm PLC write execution result
"""

from odoo import http, fields
from odoo.http import request, Response
import json
import hashlib
import logging

_logger = logging.getLogger(__name__)

class ScadaApiController(http.Controller):

    def _authenticate_gateway(self):
        """Validate the Authorization: Bearer <api_key> header against scada.gateway records."""
        auth_header = request.httprequest.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return None
        token = auth_header.split(' ', 1)[1].strip()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        gateway = request.env['scada.gateway'].sudo().search([
            ('api_key_hash', '=', token_hash),
            ('active', '=', True)
        ], limit=1)
        return gateway

    @http.route('/scada/api/v1/heartbeat', type='json', auth='none', methods=['POST'], csrf=False)
    def gateway_heartbeat(self, **kwargs):
        """Update gateway last heartbeat, version, host OS, and buffer size."""
        gateway = self._authenticate_gateway()
        if not gateway:
            return {'status': 'error', 'message': 'Unauthorized Gateway API Key'}

        data = request.get_json_data() or {}
        gateway.write({
            'last_heartbeat': fields.Datetime.now(),
            'version': data.get('version', gateway.version),
            'host_os': data.get('host_os', gateway.host_os),
            'buffer_queue_size': data.get('buffer_size', 0),
        })
        return {'status': 'ok', 'server_time': fields.Datetime.now()}

    @http.route('/scada/api/v1/config', type='http', auth='none', methods=['GET'], csrf=False)
    def get_gateway_config(self, **kwargs):
        """Return active connection and tag configuration as JSON with ETag caching."""
        gateway = self._authenticate_gateway()
        if not gateway:
            return Response(json.dumps({'error': 'Unauthorized'}), status=401, mimetype='application/json')

        connections_data = []
        for conn in gateway.connection_ids.filtered(lambda c: c.active):
            tags_data = []
            for tag in conn.tag_ids.filtered(lambda t: t.active):
                tags_data.append({
                    'code': tag.code,
                    'address': tag.address,
                    'data_type': tag.data_type,
                    'mode': tag.mode,
                    'scale': tag.scale,
                    'offset': tag.offset,
                    'poll_interval': tag.poll_interval or conn.poll_interval_default,
                })
            connections_data.append({
                'code': conn.code,
                'name': conn.name,
                'protocol': conn.protocol,
                'host': conn.host,
                'port': conn.port,
                'timeout': conn.timeout,
                'unit_id': conn.unit_id,
                'poll_interval_default': conn.poll_interval_default,
                'tags': tags_data,
            })

        payload = json.dumps({'gateway': gateway.code, 'connections': connections_data})
        etag = hashlib.md5(payload.encode()).hexdigest()

        # Return 304 Not Modified if the client already has the current config
        if request.httprequest.headers.get('If-None-Match') == etag:
            return Response(status=304)

        resp = Response(payload, status=200, mimetype='application/json')
        resp.headers['ETag'] = etag
        return resp

    @http.route('/scada/api/v1/ingest', type='json', auth='none', methods=['POST'], csrf=False)
    def ingest_telemetry(self, **kwargs):
        """
        Receive a batch of tag readings, update last-value cache, append to historian,
        and evaluate all active rules for each tag.
        """
        gateway = self._authenticate_gateway()
        if not gateway:
            return {'status': 'error', 'message': 'Unauthorized'}

        payload = request.get_json_data() or {}
        readings = payload.get('readings', [])  # list of dicts: {tag_code, value, quality, timestamp}

        if not readings:
            return {'status': 'ok', 'processed': 0}

        tag_obj = request.env['scada.tag'].sudo()
        last_obj = request.env['scada.tag.last'].sudo()
        val_obj = request.env['scada.tag.value'].sudo()
        rule_obj = request.env['scada.rule'].sudo()

        count = 0
        tag_cache = {}
        for r in readings:
            code = r.get('tag_code')
            val = r.get('value')
            quality = r.get('quality', 'good')
            ts = r.get('timestamp') or fields.Datetime.now()

            # Resolve tag from cache or DB (scoped to this gateway)
            tag = tag_cache.get(code)
            if not tag:
                tag = tag_obj.search([('code', '=', code), ('connection_id.gateway_id', '=', gateway.id)], limit=1)
                if tag:
                    tag_cache[code] = tag

            if not tag:
                continue

            # Update last-value cache (scada.tag.last)
            last = last_obj.search([('tag_id', '=', tag.id)], limit=1)
            vals = {
                'tag_id': tag.id,
                'value_str': str(val),
                'value_num': float(val) if isinstance(val, (int, float)) else 0.0,
                'quality': quality,
                'timestamp': ts,
            }
            if last:
                last.write(vals)
            else:
                last_obj.create(vals)

            # Append to historian (FR-S2)
            val_obj.create({
                'tag_id': tag.id,
                'value_str': str(val),
                'value_num': float(val) if isinstance(val, (int, float)) else 0.0,
                'quality': quality,
                'timestamp': ts,
            })

            # Evaluate all active rules linked to this tag
            rules = rule_obj.search([('tag_id', '=', tag.id), ('active', '=', True)])
            for rule in rules:
                rule.evaluate(val)

            count += 1

        return {'status': 'ok', 'processed': count}

    @http.route('/scada/api/v1/commands', type='json', auth='none', methods=['POST'], csrf=False)
    def fetch_pending_commands(self, **kwargs):
        """Return pending write commands for this gateway and mark them as sent."""
        gateway = self._authenticate_gateway()
        if not gateway:
            return {'status': 'error', 'message': 'Unauthorized'}

        requests = request.env['scada.write.request'].sudo().search([
            ('state', '=', 'pending'),
            ('tag_id.connection_id.gateway_id', '=', gateway.id)
        ], limit=50)

        commands = []
        for r in requests:
            commands.append({
                'id': r.id,
                'tag_code': r.tag_id.code,
                'address': r.tag_id.address,
                'data_type': r.tag_id.data_type,
                'value': r.requested_value,
            })
            r.write({'state': 'sent'})

        return {'status': 'ok', 'commands': commands}
