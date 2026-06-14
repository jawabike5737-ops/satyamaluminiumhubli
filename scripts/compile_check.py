import py_compile,os
errors=0
for root,dirs,files in os.walk('.'):
    if 'migrations' in root.split(os.sep):
        continue
    for f in files:
        if f.endswith('.py'):
            p=os.path.join(root,f)
            try:
                py_compile.compile(p, doraise=True)
            except Exception as e:
                print('Compile error in',p,':',e)
                errors+=1
print('Done. errors=',errors)
