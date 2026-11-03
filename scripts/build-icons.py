"""Export the approved Ambi artwork into platform icon formats."""
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
folder = root / 'desktop/shared/icons'
with Image.open(folder / 'ambi-source.png') as source:
    icon = source.convert('RGBA').resize((1024, 1024), Image.Resampling.LANCZOS)
    icon.save(folder / 'ambi.png')
    icon.save(folder / 'ambi.icns', format='ICNS')
    icon.save(folder / 'ambi.ico', format='ICO', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    icon.resize((64, 64), Image.Resampling.LANCZOS).save(root / 'ui/public/ambi-icon.png')
print('Exported PNG, ICNS, ICO and web icon from the shared Ambi artwork.')
