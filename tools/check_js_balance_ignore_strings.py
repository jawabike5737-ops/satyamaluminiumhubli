from html.parser import HTMLParser
pfile='c:/Users/HP/OneDrive/Desktop/satyamaluminiumhubli/templates/create_quotation.html'
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
blk = s.scripts[5]  # block 6 (0-based index 5)

opens = {'(':')','{':'}','[':']'}
stack=[]
escaped=False
in_single=False
in_double=False
in_back=False
for i,ch in enumerate(blk):
    if escaped:
        escaped=False; continue
    if ch=='\\': escaped=True; continue
    if in_single:
        if ch=="'": in_single=False
        continue
    if in_double:
        if ch=='"': in_double=False
        continue
    if in_back:
        if ch=='`': in_back=False
        continue
    if ch=="'": in_single=True; continue
    if ch=='"': in_double=True; continue
    if ch=='`': in_back=True; continue
    if ch in opens:
        stack.append((ch,i))
    elif ch in [')','}',']']:
        if stack and opens[stack[-1][0]]==ch:
            stack.pop()
        else:
            print('Mismatch closing',ch,'at',i)
            break

print('Remaining opens:',stack[:10])
if stack:
    print('\nContext near first unmatched:')
    idx=stack[-1][1]
    print(blk[max(0,idx-120):idx+120])
