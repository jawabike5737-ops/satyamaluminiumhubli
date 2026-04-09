Place a Unicode TTF here so ReportLab can render the rupee (₹) symbol.

Recommended font: DejaVuSans.ttf

Options:
1) Manually download DejaVuSans.ttf and copy it to this folder (`fonts/DejaVuSans.ttf`).
   Official source (GitHub):
   https://github.com/dejavu-fonts/dejavu-fonts/tree/master/ttf

2) Use the provided PowerShell script from the project root to download automatically:
   .\scripts\download_dejavu.ps1

After placing the TTF, regenerate PDFs — the application will register the font and render ₹ correctly.

If you cannot add the file to the repository, you can also install the font on your system (Windows Fonts) and the helper will try common system paths as a fallback.