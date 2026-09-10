import sqlite3, os
p=r"c:\Users\HP\OneDrive\Desktop\satyam_project\satyam_project\db.sqlite3"
conn=sqlite3.connect(p)
c=conn.cursor()
print('tables before:')
c.execute("SELECT name FROM sqlite_master WHERE type='table';")
print('\n'.join(sorted([r[0] for r in c.fetchall()])))
# check for core_quotationterm
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='core_quotationterm'")
if not c.fetchone():
    print('core_quotationterm missing — creating table')
    c.execute('''CREATE TABLE core_quotationterm (
        id integer PRIMARY KEY AUTOINCREMENT,
        "order" integer NOT NULL DEFAULT 0,
        quotation_id integer NOT NULL,
        term_id integer NOT NULL
    );''')
    c.execute('CREATE INDEX IF NOT EXISTS core_quotationterm_quotation_id_idx ON core_quotationterm(quotation_id);')
    c.execute('CREATE INDEX IF NOT EXISTS core_quotationterm_term_id_idx ON core_quotationterm(term_id);')
    conn.commit()
    print('table created')
else:
    print('core_quotationterm already exists')
print('tables after:')
c.execute("SELECT name FROM sqlite_master WHERE type='table';")
print('\n'.join(sorted([r[0] for r in c.fetchall()])))
conn.close()
