{
    'name': 'Aluminum Inventory',
    'version': '1.0',
    'summary': 'Aluminum windows manufacturing extensions to Inventory',
    'description': """
Adds aluminum-windows-manufacturing-specific tracking to stock.lot:
lot length, whether the lot was purchased or is a leftover return, and a
link back to the parent stick a leftover was cut from.
""",
    'category': 'Inventory',
    'depends': ['stock'],
    'data': [
        'views/stock_lot_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
