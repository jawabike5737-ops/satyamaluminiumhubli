from html.parser import HTMLParser
pfile=r'c:/Users/HP/OneDrive/Desktop/satyamaluminiumhubli/templates/create_quotation.html'
class S(HTMLParser):
    def __init__(self):
        super().__init__(); self.scripts=[]; self._in=False; self._data=[]
    def handle_starttag(self, tag, attrs):
        if tag=='script': self._in=True; self._data=[]
    def handle_endtag(self, tag):
        if tag=='script' and self._in:
            self.scripts.append('\n'.join(self._data)); self._in=False
    def handle_data(self,data):
        if self._in: self._data.append(data)

s=S(); s.feed(open(pfile,encoding='utf-8').read())
print('Found', len(s.scripts), 'script blocks')
for i,blk in enumerate(s.scripts,1):
    b={'(':0,'{':0,'[':0}
    for c in blk:
        if c in b: b[c]+=1
        elif c==')': b['(']-=1
        elif c=='}': b['{']-=1
        elif c==']': b['[']-=1
    print('Block',i,'len',len(blk),'balances:',b)
    if any(v!=0 for v in b.values()):
        print('\n--- Unbalanced Block',i,'---\n')
        print(blk)
        break
else:
    print('All script blocks balanced (paren/brace/bracket counts)')
