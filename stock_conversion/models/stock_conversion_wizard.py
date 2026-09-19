# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare


class StockConversionConfirmWizard(models.TransientModel):
    _name = 'stock.conversion.confirm.wizard'
    _description = 'Confirm Finished Goods Quantities'

    conversion_id = fields.Many2one(
        'stock.conversion', string='Stock Conversion', required=True, readonly=True, ondelete='cascade')
    raw_material_id = fields.Many2one(related='conversion_id.raw_material_id', readonly=True)
    raw_material_qty = fields.Float(
        related='conversion_id.raw_material_qty', readonly=True, digits='Product Unit of Measure')
    raw_material_uom_id = fields.Many2one(related='conversion_id.raw_material_uom_id', readonly=True)

    line_ids = fields.One2many(
        'stock.conversion.confirm.wizard.line', 'wizard_id', string='Finished Goods')

    total_done_qty = fields.Float(
        string='Total Done Qty', compute='_compute_totals', digits='Product Unit of Measure')
    scrap_qty_preview = fields.Float(
        string='Yield Loss / Scrap Qty', compute='_compute_totals', digits='Product Unit of Measure')
    yield_percent_preview = fields.Float(string='Yield %', compute='_compute_totals')
    scrap_percent_preview = fields.Float(string='Loss / Scrap %', compute='_compute_totals')

    @api.depends('line_ids.done_qty', 'line_ids.product_uom_id', 'raw_material_qty', 'raw_material_uom_id')
    def _compute_totals(self):
        for wiz in self:
            total = 0.0
            for line in wiz.line_ids:
                if line.product_uom_id and wiz.raw_material_uom_id:
                    total += line.product_uom_id._compute_quantity(
                        line.done_qty, wiz.raw_material_uom_id, round=False)
                else:
                    total += line.done_qty
            scrap_qty = max(wiz.raw_material_qty - total, 0.0)
            wiz.total_done_qty = total
            wiz.scrap_qty_preview = scrap_qty
            wiz.yield_percent_preview = (total / wiz.raw_material_qty * 100.0) if wiz.raw_material_qty else 0.0
            wiz.scrap_percent_preview = (scrap_qty / wiz.raw_material_qty * 100.0) if wiz.raw_material_qty else 0.0

    def action_confirm(self):
        """Write the confirmed Done Quantities back onto the real
        conversion_line_ids, then run the actual stock/valuation work.
        This is the one explicit checkpoint between "what we planned" and
        "what we're about to move and value" - nothing is scrapped,
        consumed or put away before this button is clicked."""
        self.ensure_one()
        rounding = self.raw_material_uom_id.rounding or 0.01

        if not self.line_ids:
            raise UserError(_('Please confirm a Done Quantity for at least one finished product.'))
        for line in self.line_ids:
            line_rounding = line.product_uom_id.rounding or 0.01
            if float_compare(line.done_qty, 0.0, precision_rounding=line_rounding) <= 0:
                raise UserError(_(
                    'Done Quantity for %s must be greater than zero. Remove the line instead '
                    'if nothing was produced for it.'
                ) % line.finished_product_id.display_name)
        if float_compare(self.total_done_qty, self.raw_material_qty, precision_rounding=rounding) > 0:
            raise UserError(_(
                'Total Done Quantity (%(done)s) cannot exceed the Raw Material Quantity '
                '(%(raw)s).'
            ) % {'done': '%.4f' % self.total_done_qty, 'raw': '%.4f' % self.raw_material_qty})

        for line in self.line_ids:
            line.conversion_line_id.product_qty = line.done_qty

        self.conversion_id._action_validate_confirmed()

        return {
            'type': 'ir.actions.act_window',
            'name': self.conversion_id.name,
            'res_model': 'stock.conversion',
            'view_mode': 'form',
            'res_id': self.conversion_id.id,
            'target': 'current',
        }


class StockConversionConfirmWizardLine(models.TransientModel):
    _name = 'stock.conversion.confirm.wizard.line'
    _description = 'Confirm Finished Goods Quantities - Line'

    wizard_id = fields.Many2one(
        'stock.conversion.confirm.wizard', required=True, ondelete='cascade')
    conversion_line_id = fields.Many2one(
        'stock.conversion.line', string='Finished Goods Line', required=True, readonly=True, ondelete='cascade')

    finished_product_id = fields.Many2one(related='conversion_line_id.finished_product_id', readonly=True)
    destination_location_id = fields.Many2one(related='conversion_line_id.destination_location_id', readonly=True)
    product_uom_id = fields.Many2one(related='conversion_line_id.product_uom_id', readonly=True)
    planned_qty = fields.Float(
        related='conversion_line_id.product_qty', readonly=True, string='Planned Qty',
        digits='Product Unit of Measure',
    )
    done_qty = fields.Float(string='Done Qty', digits='Product Unit of Measure')
