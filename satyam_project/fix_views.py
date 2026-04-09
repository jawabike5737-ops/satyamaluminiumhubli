import io,sys,re
p=r"c:\Users\HP\OneDrive\Desktop\satyam_project\satyam_project\core\views.py"
s=open(p,'rb').read()
# remove NUL bytes
if b'\x00' in s:
    s=s.replace(b'\x00',b'')
# convert to text
txt=s.decode('utf-8',errors='replace')
# locate the return render block for create_quotation and the following header
start_pattern = "return render(request, 'create_quotation.html',"
header_pattern = "# ================= LIST PAGE ================="
si = txt.find(start_pattern)
hi = txt.find(header_pattern)
if si!=-1 and hi!=-1 and hi>si:
    # find the end of the render(...) call by locating the first occurrence of '\n    })' after si
    close_idx = txt.find('\n    })', si)
    if close_idx==-1:
        close_idx = txt.find('\n})', si)
    if close_idx!=-1 and close_idx < hi:
        # keep up to the end of the closing '})' (include it)
        new_txt = txt[:close_idx+5] + '\n\n' + txt[hi:]
        open(p,'w',encoding='utf-8').write(new_txt)
        print('stray_block_removed')
    else:
        # fallback: remove between end of the render call's closing brace '})' (search backwards)
        prev_close = txt.rfind('})', 0, hi)
        if prev_close!=-1:
            new_txt = txt[:prev_close+2] + '\n\n' + txt[hi:]
            open(p,'w',encoding='utf-8').write(new_txt)
            print('stray_block_removed_by_fallback')
        else:
            print('could_not_find_closing_brace')
else:
    # just write cleaned file back (remove NULs)
    open(p,'wb').write(s)
    print('nul_removed_only_or_patterns_not_found')
