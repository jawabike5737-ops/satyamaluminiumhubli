"""
Script to replace bare 'except Exception:' with logged 'except Exception as e:'
and insert a logging.exception() call as the first statement in the except block.
This performs minimal, safe text transformations (keeps existing fallbacks).
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(__file__))

py_files = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    # skip migrations and hidden dirs
    if 'migrations' in dirpath.split(os.sep):
        continue
    if dirpath.endswith('site-packages'):
        continue
    for fn in filenames:
        if fn.endswith('.py'):
            py_files.append(os.path.join(dirpath, fn))

pattern = re.compile(r"^\s*except\s+Exception\s*:\s*$", re.MULTILINE)

for path in py_files:
    try:
        with io.open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        logger.exception('Unhandled exception: %s', e)
        continue

    if 'except Exception:' not in text:
        continue

    orig = text
    lines = text.splitlines()
    new_lines = []
    changed = False
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"(\s*)except\s+Exception\s*:\s*$", line)
        if m:
            indent = m.group(1)
            # replace header
            new_lines.append(f"{indent}except Exception as e:")
            # prepare logging insertion
            log_line = f"{indent}    logger.exception('Unhandled exception: %s', e)"
            # check next line: if 'pass' or already logging
            next_idx = i + 1
            if next_idx < len(lines):
                next_line = lines[next_idx]
                stripped = next_line.strip()
                if stripped == 'pass':
                    # replace pass with logging and a safe continue (keep pass removed)
                    new_lines.append(log_line)
                    # skip the pass line
                    i = next_idx
                elif 'logger.exception' in next_line or 'logging.exception' in next_line:
                    # already has logging, keep as is
                    pass
                else:
                    # insert logging before existing except body
                    new_lines.append(log_line)
            else:
                new_lines.append(log_line)
            changed = True
            i += 1
            continue
        else:
            new_lines.append(line)
            i += 1

    if not changed:
        continue

    new_text = '\n'.join(new_lines)
    # ensure module has import logging and logger defined
    if 'import logging' not in new_text:
        # try to insert after other imports at top
        new_text = re.sub(r"((?:from\s+[\w\.]+\s+import\s+.+\n|import\s+.+\n)+)", r"\1import logging\n", new_text, count=1)
    if re.search(r"logger\s*=\s*logging.getLogger\(__name__\)", new_text) is None:
        # add logger after imports
        new_text = re.sub(r"((?:from\s+[\w\.]+\s+import\s+.+\n|import\s+.+\n)+)import logging\n", r"\1import logging\nlogger = logging.getLogger(__name__)\n", new_text, count=1)

    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(new_text)
    print('Patched', path)

print('Done')