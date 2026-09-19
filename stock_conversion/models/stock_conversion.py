# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round


class StockConversion(models.Model):
    _name = 'stock.conversion'
    _description = 'Stock Conversion / Pack & Convert'
    _order = 'id desc'
    _check_company_auto = True

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New'),
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company,
    )
    date = fields.Datetime(string='Date', required=True, default=fields.Datetime.now)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', copy=False, tracking=True, required=True)

    source_location_id = fields.Many2one(
        'stock.location', string='Source Location', required=True,
        domain="[('usage', '=', 'internal')]", check_company=True,
        help='Location the raw material is currently stored in, '
             'e.g. Main Warehouse/Stock or a Van Stock location.',
    )
    processing_location_id = fields.Many2one(
        'stock.location', string='Processing Location', required=True,
        domain="[('usage', '=', 'internal')]", check_company=True,
        help='Intermediate location where raw material is staged before '
             'conversion, e.g. WH/Processing.',
    )
    scrap_location_id = fields.Many2one(
        'stock.location', string='Scrap / Loss Location', required=True,
        domain="[('scrap_location', '=', True)]", check_company=True,
    )

    raw_material_id = fields.Many2one(
        'product.product', string='Raw Material', required=True,
        domain="[('type', 'in', ('product', 'consu'))]", check_company=True,
    )
    raw_material_qty = fields.Float(
        string='Raw Material Quantity', required=True, digits='Product Unit of Measure',
    )
    raw_material_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True)

    conversion_line_ids = fields.One2many(
        'stock.conversion.line', 'conversion_id', string='Finished Goods Lines', copy=True,
    )

    total_output_qty = fields.Float(
        string='Total Output Qty', compute='_compute_totals', store=True,
        digits='Product Unit of Measure',
        help='Sum of all finished goods output quantities, converted to the '
             'raw material unit of measure.',
    )
    scrap_qty = fields.Float(
        string='Yield Loss / Scrap Qty', compute='_compute_totals', store=True,
        digits='Product Unit of Measure',
        help='Raw Material Quantity minus Total Output Qty. Routed to the '
             'Scrap / Loss Location when the conversion is validated.',
    )
    yield_percent = fields.Float(string='Yield %', compute='_compute_totals', store=True)

    company_currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    total_raw_material_cost = fields.Monetary(
        string='Consumed Raw Material Cost', copy=False, readonly=True,
        currency_field='company_currency_id',
        help='Actual inventory cost consumed from the Processing location, '
             'captured from the stock valuation layer(s) created when the '
             'conversion was validated.',
    )

    processing_picking_id = fields.Many2one('stock.picking', string='Move to Processing', readonly=True, copy=False)
    consumption_move_id = fields.Many2one('stock.move', string='Consumption Move', readonly=True, copy=False)
    scrap_id = fields.Many2one('stock.scrap', string='Scrap Record', readonly=True, copy=False)
    output_picking_ids = fields.One2many(
        'stock.picking', 'stock_conversion_id', string='Finished Goods Transfers', readonly=True,
    )
    move_count = fields.Integer(compute='_compute_move_count', string='Move Count')

    notes = fields.Text(string='Notes')

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('conversion_line_ids.product_qty', 'conversion_line_ids.product_uom_id',
                 'raw_material_qty', 'raw_material_uom_id')
    def _compute_totals(self):
        for rec in self:
            total = 0.0
            for line in rec.conversion_line_ids:
                if line.product_uom_id and rec.raw_material_uom_id:
                    total += line.product_uom_id._compute_quantity(
                        line.product_qty, rec.raw_material_uom_id, round=False)
                else:
                    total += line.product_qty
            rec.total_output_qty = total
            rec.scrap_qty = max(rec.raw_material_qty - total, 0.0)
            rec.yield_percent = (total / rec.raw_material_qty * 100.0) if rec.raw_material_qty else 0.0

    def _compute_move_count(self):
        for rec in self:
            count = 0
            if rec.processing_picking_id:
                count += 1
            if rec.consumption_move_id:
                count += 1
            if rec.scrap_id:
                count += 1
            count += len(rec.output_picking_ids)
            rec.move_count = count

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stock.conversion') or _('New')
        return super().create(vals_list)

    def unlink(self):
        for rec in self:
            if rec.state not in ('draft', 'cancel'):
                raise UserError(_('Only draft or cancelled conversions can be deleted. '
                                   'Cancel "%s" first.') % rec.name)
        return super().unlink()

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('raw_material_qty')
    def _check_raw_material_qty(self):
        for rec in self:
            rounding = rec.raw_material_uom_id.rounding or 0.01
            if float_compare(rec.raw_material_qty, 0.0, precision_rounding=rounding) <= 0:
                raise ValidationError(_('Raw Material Quantity must be greater than zero.'))

    @api.constrains('conversion_line_ids', 'raw_material_qty', 'raw_material_uom_id')
    def _check_output_not_exceeding_input(self):
        for rec in self:
            if not rec.conversion_line_ids:
                continue
            rounding = rec.raw_material_uom_id.rounding or 0.01
            if float_compare(rec.total_output_qty, rec.raw_material_qty, precision_rounding=rounding) > 0:
                raise ValidationError(_(
                    'Total finished goods output quantity (%(output)s) cannot exceed the '
                    'raw material quantity (%(raw)s) for %(name)s.'
                ) % {
                    'output': '%.4f' % rec.total_output_qty,
                    'raw': '%.4f' % rec.raw_material_qty,
                    'name': rec.name,
                })

    @api.constrains('source_location_id', 'processing_location_id')
    def _check_locations_different(self):
        for rec in self:
            if rec.source_location_id and rec.source_location_id == rec.processing_location_id:
                raise ValidationError(_('Source Location and Processing Location must be different.'))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_internal_picking_type(self):
        self.ensure_one()
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not picking_type:
            raise UserError(_(
                'No "Internal Transfer" operation type could be found for company %s. '
                'Please configure one under Inventory > Configuration > Operations Types.'
            ) % self.company_id.display_name)
        return picking_type

    def _get_production_location(self):
        """Return the virtual 'Production' location used internally to move
        stock through while its value is being re-costed from raw material
        to finished goods. This is the same stock.location.usage='production'
        location the Manufacturing app relies on; it exists in base `stock`
        data regardless of whether MRP is installed."""
        self.ensure_one()
        location = self.env.ref('stock.location_production', raise_if_not_found=False)
        if not location or (location.company_id and location.company_id != self.company_id):
            location = self.env['stock.location'].search([
                ('usage', '=', 'production'),
                '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id),
            ], limit=1)
        if not location:
            raise UserError(_(
                'No virtual "Production" location could be found for company %s. Stock '
                'Conversion uses this location internally to record the consumption of '
                'raw materials and the creation of finished goods. Please make sure a '
                'location with usage type "Production" exists (Inventory > Configuration '
                '> Locations, with Storage Locations enabled).'
            ) % self.company_id.display_name)
        return location

    def _get_available_qty(self, product, location):
        return product.with_context(location=location.id).qty_available

    def _validate_picking(self, picking):
        """Fully validate an internal transfer. button_validate() is the
        public, supported entry point for this (as opposed to the private
        stock.move._action_done()); it can, in principle, return a wizard
        action instead of completing synchronously (e.g. if a product
        unexpectedly requires lots/serials, or reservation didn't cover the
        full demand). Since every move here is created with picked=True and
        its full demand already reserved, that should never happen - but we
        fail loudly instead of silently leaving the picking half-done if it
        ever does."""
        result = picking.button_validate()
        if isinstance(result, dict):
            raise UserError(_(
                'Validating the internal transfer %(picking)s triggered an unexpected '
                'confirmation step instead of completing directly (dialog: %(name)s). This '
                'usually means a product requires lots/serial numbers that were not set, or '
                'stock changed between the availability check and validation. Please open '
                'the transfer "%(picking)s" directly under Inventory > Operations > Transfers '
                'to resolve it, then retry.'
            ) % {'picking': picking.name, 'name': result.get('name') or result.get('res_model') or ''})
        return result

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------
    def action_process(self):
        """Move the raw material from the Source Location into the
        Processing Location using a standard internal stock.picking."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft conversions can be moved to processing.'))
            if not rec.conversion_line_ids:
                raise UserError(_('Please add at least one Finished Goods line before processing.'))

            rounding = rec.raw_material_uom_id.rounding or 0.01
            available = rec._get_available_qty(rec.raw_material_id, rec.source_location_id)
            if float_compare(available, rec.raw_material_qty, precision_rounding=rounding) < 0:
                raise UserError(_(
                    'Not enough stock of %(product)s at %(location)s. '
                    'Available: %(available).4f, Required: %(required).4f.'
                ) % {
                    'product': rec.raw_material_id.display_name,
                    'location': rec.source_location_id.display_name,
                    'available': available,
                    'required': rec.raw_material_qty,
                })

            picking_type = rec._get_internal_picking_type()
            picking = self.env['stock.picking'].create({
                'picking_type_id': picking_type.id,
                'location_id': rec.source_location_id.id,
                'location_dest_id': rec.processing_location_id.id,
                'origin': rec.name,
                'company_id': rec.company_id.id,
                'move_ids': [(0, 0, {
                    'name': rec.name,
                    'product_id': rec.raw_material_id.id,
                    'product_uom_qty': rec.raw_material_qty,
                    'product_uom': rec.raw_material_uom_id.id,
                    'location_id': rec.source_location_id.id,
                    'location_dest_id': rec.processing_location_id.id,
                    'company_id': rec.company_id.id,
                })],
            })
            picking.action_confirm()
            picking.action_assign()
            # Odoo 17+: there is no "quantity_done" field on stock.move anymore.
            # _action_assign() already reserved the full demand into each move
            # line's `quantity` (guaranteed by the availability check above);
            # `picked = True` is what marks that reserved quantity as actually
            # moved rather than merely reserved.
            picking.move_ids.picked = True
            rec._validate_picking(picking)

            rec.processing_picking_id = picking.id
            rec.state = 'processing'
        return True

    def action_validate(self):
        """Scrap the yield-loss portion of the raw material, consume the
        remainder into the virtual Production location, then re-issue it as
        the finished goods lines into their destinations, allocating the
        actual consumed cost across the lines."""
        for rec in self:
            if rec.state != 'processing':
                raise UserError(_('Only conversions in Processing state can be validated.'))
            if not rec.conversion_line_ids:
                raise UserError(_('Please add at least one Finished Goods line before validating.'))

            rounding = rec.raw_material_uom_id.rounding or 0.01
            available = rec._get_available_qty(rec.raw_material_id, rec.processing_location_id)
            if float_compare(available, rec.raw_material_qty, precision_rounding=rounding) < 0:
                raise UserError(_(
                    'Not enough stock of %(product)s at %(location)s to complete the '
                    'conversion. Available: %(available).4f, Required: %(required).4f.'
                ) % {
                    'product': rec.raw_material_id.display_name,
                    'location': rec.processing_location_id.display_name,
                    'available': available,
                    'required': rec.raw_material_qty,
                })

            production_location = rec._get_production_location()

            # 1) Route the yield-loss / scrap portion of the RAW MATERIAL out
            #    of the Processing location via the native stock.scrap model,
            #    so Odoo's own valuation/accounting engine records the loss
            #    at the product's current cost.
            if float_compare(rec.scrap_qty, 0.0, precision_rounding=rounding) > 0:
                scrap = self.env['stock.scrap'].create({
                    'product_id': rec.raw_material_id.id,
                    'product_uom_id': rec.raw_material_uom_id.id,
                    'scrap_qty': rec.scrap_qty,
                    'location_id': rec.processing_location_id.id,
                    'scrap_location_id': rec.scrap_location_id.id,
                    'company_id': rec.company_id.id,
                    'origin': rec.name,
                })
                scrap.do_scrap()
                rec.scrap_id = scrap.id

            # 2) Consume the remaining raw material into the virtual
            #    Production location. This is a plain outgoing move, so
            #    stock_account automatically creates the negative stock
            #    valuation layer / accounting entry using the product's
            #    real FIFO/AVCO cost - no guessing involved.
            consume_qty = rec.total_output_qty
            consumption_move = self.env['stock.move'].create({
                'name': _('%s - Convert') % rec.name,
                'product_id': rec.raw_material_id.id,
                'product_uom_qty': consume_qty,
                'product_uom': rec.raw_material_uom_id.id,
                'location_id': rec.processing_location_id.id,
                'location_dest_id': production_location.id,
                'company_id': rec.company_id.id,
                'origin': rec.name,
            })
            consumption_move._action_confirm()
            consumption_move._action_assign()
            consumption_move.picked = True
            consumption_move._action_done()
            rec.consumption_move_id = consumption_move.id

            svls = self.env['stock.valuation.layer'].search([('stock_move_id', '=', consumption_move.id)])
            consumed_value = abs(sum(svls.mapped('value')))
            rec.total_raw_material_cost = consumed_value

            # 3) Allocate the consumed cost across the finished-goods lines
            #    and move each of them out of the virtual Production
            #    location into its destination. The allocated unit cost is
            #    forced onto the move's price_unit before validating it -
            #    the same mechanism Odoo Manufacturing itself uses to value
            #    produced goods - so stock_account values the resulting
            #    stock valuation layer accordingly.
            lines = rec.conversion_line_ids.filtered(
                lambda l: not float_is_zero(l.product_qty, precision_rounding=l.product_uom_id.rounding or 0.01))
            total_ratio = sum(lines.mapped('cost_allocation_ratio')) or 100.0
            picking_type = rec._get_internal_picking_type()
            pickings = self.env['stock.picking']
            allocated_so_far = 0.0

            for index, line in enumerate(lines, start=1):
                if index == len(lines):
                    # Assign any rounding remainder to the last line so the
                    # allocated total always reconciles with consumed_value.
                    allocated_cost = consumed_value - allocated_so_far
                else:
                    allocated_cost = float_round(
                        consumed_value * (line.cost_allocation_ratio / total_ratio), precision_digits=4)
                allocated_so_far += allocated_cost
                unit_cost = (allocated_cost / line.product_qty) if line.product_qty else 0.0

                picking = self.env['stock.picking'].create({
                    'picking_type_id': picking_type.id,
                    'location_id': production_location.id,
                    'location_dest_id': line.destination_location_id.id,
                    'origin': rec.name,
                    'company_id': rec.company_id.id,
                    'stock_conversion_id': rec.id,
                    'move_ids': [(0, 0, {
                        'name': _('%(ref)s - %(product)s') % {
                            'ref': rec.name, 'product': line.finished_product_id.display_name},
                        'product_id': line.finished_product_id.id,
                        'product_uom_qty': line.product_qty,
                        'product_uom': line.product_uom_id.id,
                        'location_id': production_location.id,
                        'location_dest_id': line.destination_location_id.id,
                        'company_id': rec.company_id.id,
                        'price_unit': unit_cost,
                    })],
                })
                picking.action_confirm()
                picking.action_assign()
                for move in picking.move_ids:
                    move.price_unit = unit_cost
                picking.move_ids.picked = True
                rec._validate_picking(picking)

                line.write({'unit_cost': unit_cost, 'allocated_cost': allocated_cost})
                pickings |= picking

            rec.output_picking_ids = [(6, 0, pickings.ids)]
            rec.state = 'done'
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_('A completed conversion cannot be cancelled directly. '
                                   'Reverse the generated stock moves manually if needed.'))
            rec.state = 'cancel'
        return True

    def action_draft(self):
        for rec in self:
            if rec.state != 'cancel':
                raise UserError(_('Only cancelled conversions can be reset to draft.'))
            rec.write({
                'state': 'draft',
                'processing_picking_id': False,
            })
        return True

    def action_view_moves(self):
        self.ensure_one()
        picking_ids = self.output_picking_ids.ids
        if self.processing_picking_id:
            picking_ids.append(self.processing_picking_id.id)
        action = self.env['ir.actions.act_window']._for_xml_id('stock.action_picking_tree_all')
        action['domain'] = [('id', 'in', picking_ids)]
        action['context'] = {}
        return action


class StockConversionLine(models.Model):
    _name = 'stock.conversion.line'
    _description = 'Stock Conversion Finished Goods Line'
    _check_company_auto = True

    conversion_id = fields.Many2one(
        'stock.conversion', string='Conversion', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='conversion_id.company_id', store=True, readonly=True)

    finished_product_id = fields.Many2one(
        'product.product', string='Finished Product', required=True,
        domain="[('type', 'in', ('product', 'consu'))]", check_company=True,
    )
    destination_location_id = fields.Many2one(
        'stock.location', string='Destination Location', required=True,
        domain="[('usage', '=', 'internal')]", check_company=True,
    )
    product_qty = fields.Float(string='Quantity', required=True, digits='Product Unit of Measure')
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True)

    manual_ratio = fields.Boolean(
        string='Manual Cost %',
        help='Tick to set the cost allocation percentage manually instead of '
             'letting it be computed automatically from the relative output '
             'quantities.',
    )
    cost_allocation_ratio = fields.Float(
        string='Cost Allocation %', compute='_compute_cost_allocation_ratio',
        store=True, readonly=False, digits=(5, 2),
        help='Percentage of the consumed raw material cost allocated to this '
             'finished product. Defaults to this line\'s share of total '
             'output quantity (converted to the raw material UoM), but can '
             'be overridden manually by ticking "Manual Cost %".',
    )

    unit_cost = fields.Float(string='Unit Cost', readonly=True, copy=False, digits='Product Price')
    allocated_cost = fields.Float(string='Allocated Cost', readonly=True, copy=False, digits='Product Price')

    @api.depends('product_qty', 'product_uom_id', 'manual_ratio',
                 'conversion_id.conversion_line_ids.product_qty',
                 'conversion_id.conversion_line_ids.product_uom_id',
                 'conversion_id.raw_material_uom_id')
    def _compute_cost_allocation_ratio(self):
        for line in self:
            if line.manual_ratio:
                continue
            siblings = line.conversion_id.conversion_line_ids
            raw_uom = line.conversion_id.raw_material_uom_id
            total = 0.0
            for sibling in siblings:
                if sibling.product_uom_id and raw_uom:
                    total += sibling.product_uom_id._compute_quantity(sibling.product_qty, raw_uom, round=False)
                else:
                    total += sibling.product_qty
            if raw_uom and line.product_uom_id:
                own_qty = line.product_uom_id._compute_quantity(line.product_qty, raw_uom, round=False)
            else:
                own_qty = line.product_qty
            line.cost_allocation_ratio = (own_qty / total * 100.0) if total else 0.0

    @api.constrains('product_qty')
    def _check_product_qty(self):
        for line in self:
            rounding = line.product_uom_id.rounding or 0.01
            if float_compare(line.product_qty, 0.0, precision_rounding=rounding) <= 0:
                raise ValidationError(_('Finished product quantity must be greater than zero.'))
