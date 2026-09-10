import ast,sys
p='core/views.py'
s=open(p,encoding='utf-8').read()
try:
    ast.parse(s)
    print('AST parsed OK')
except SyntaxError as e:
    print('SyntaxError:', e)
    print('Line:', e.lineno)
    lo = max(1, e.lineno-5)
    hi = e.lineno+5
    lines = s.splitlines()
    for i in range(lo-1, min(len(lines), hi)):
        print(f"{i+1:04d}: {lines[i]}")
    sys.exit(1)
