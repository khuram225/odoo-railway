def migrate(cr, version):
    """Step 3 adds colours to print lines: text sections created before it default to 4/4."""
    cr.execute("""
        UPDATE print_estimate_page p SET colours_back = 4
          FROM print_page_type t
         WHERE p.page_type_id = t.id AND t.kind = 'text' AND COALESCE(p.colours_back, 0) = 0
    """)
