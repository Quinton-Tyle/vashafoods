# -*- coding: utf-8 -*-
{
    'name': 'Stock Conversion / Pack & Convert',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Convert raw materials into one or more finished products without using Manufacturing (MRP)',
    'description': """
Stock Conversion / Pack & Convert
==================================
A lightweight alternative to the Manufacturing (MRP) app for simple
transformation flows: raw material in, one or more finished products
out, with automatic yield-loss/scrap handling and inventory valuation.

Typical use cases: butchery/portioning (primal cut -> steak/mince/strips),
repackaging (bulk -> retail units), simple kitting or bulk-to-unit
conversions where a full Bill of Materials / routing is overkill.

Key features
------------
* Draft -> Processing -> Done workflow with a dedicated sequence.
* Moves raw material from any internal source location into an
  intermediate Processing location, using standard stock.picking /
  stock.move records.
* One or many finished-goods output lines, each with its own
  destination location and quantity.
* Automatic yield loss / scrap quantity (Raw Qty - Total Output Qty),
  routed to a configurable Scrap location via the native stock.scrap
  model.
* Consumed raw material cost is captured from the real stock
  valuation layer created when the material is issued to the virtual
  Production location, then allocated across the finished-goods lines
  by weight/quantity ratio (editable per line) and applied as the
  forced cost of each output stock move - keeping Stock on Hand,
  Inventory Valuation and Accounting journal entries consistent.
* Guardrails preventing processing/validation without sufficient
  on-hand stock.
* Smart button to jump to all generated stock moves.
""",
    'author': 'Tyle Software Solutions Ltd.',
    'website': 'https://tylesoftware.com',
    'license': 'LGPL-3',
    'depends': ['stock', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/stock_conversion_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
