p='core/views.py'
with open(p,encoding='utf-8') as f:
    lines=f.readlines()

tries=[]
for i,l in enumerate(lines,1):
    stripped=l.lstrip('\t ')
    indent=len(l)-len(stripped)
    if stripped.startswith('try:'):
        tries.append((i,indent))
    if stripped.startswith('except') or stripped.startswith('finally'):
        # find most recent try with same indent
        for j in range(len(tries)-1,-1,-1):
            ti,ind=tries[j]
            if ind==indent:
                # matched
                tries.pop(j)
                break

print('Unmatched try statements:')
for ti,ind in tries:
    print(ti, ind, lines[ti-1].rstrip())
