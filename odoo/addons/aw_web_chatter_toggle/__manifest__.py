# -*- coding: utf-8 -*-
{
    'name': 'Chatter Toggle',
    'version': '19.0.1.0.0',
    'category': 'Hidden/Tools',
    'summary': 'Collapse the chatter to an icon bar on every form view',
    'description': """
A toggle at the top of the chatter collapses it to a narrow icon bar and
restores it. The choice is remembered in the browser (localStorage) and
applies to every form view. Nothing about the chatter's content or
behaviour changes. Independent of the fenestration modules.
    """,
    'author': 'Khurram',
    'license': 'LGPL-3',
    'depends': ['mail'],
    # Installs itself the next time the modules are upgraded.
    'auto_install': True,
    'data': [],
    'assets': {
        'web.assets_backend': [
            'aw_web_chatter_toggle/static/src/**/*.js',
            'aw_web_chatter_toggle/static/src/**/*.xml',
            'aw_web_chatter_toggle/static/src/**/*.scss',
        ],
    },
    'installable': True,
    'application': False,
}
