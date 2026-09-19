# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = 'product.category'

    property_stock_scrap_account_id = fields.Many2one(
        'account.account', string='Scrap / Loss Account', company_dependent=True,
        domain="[('deprecated', '=', False)]",
        help='GL account debited when products in this category are scrapped as yield '
             'loss through Stock Conversion. When set, this is applied automatically onto '
             'a Scrap / Loss Location the first time it is used with this category, so '
             'scrap posts to a dedicated loss account instead of the generic Stock Output '
             'account. If a location is later configured with a different account by hand, '
             'the mismatch is flagged rather than silently overridden.',
    )
