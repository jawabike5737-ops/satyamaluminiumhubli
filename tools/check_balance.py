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
for i,blk in enumerate(s.scripts,1):
    stack=[]
    opens={'(':')','{':'}','[':']'}
    for idx,ch in enumerate(blk):
        if ch in opens:
            stack.append((ch,idx))
        elif ch in [')','}',']']:
            if stack and opens[stack[-1][0]]==ch:
                stack.pop()
            else:
                print('Block',i,'Mismatch at idx',idx,'char',ch)
                break
    if stack:
        print('Block',i,'unmatched opens (last 10):',[(c,pos) for c,pos in stack[-10:]])
        print('--- Context near end (200 chars) ---')
        print(blk[-200:])
        break
else:
    print('All balanced')
