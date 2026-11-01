"""Add the supplied Ambi controller to the v2 source pack using Rive CLI 1.8.0.
Usage: python3 ui/scripts/build-rive-controller.py SOURCE_PACK RIVE_CLI
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

source, cli = map(lambda value: Path(value).resolve(), sys.argv[1:])
with tempfile.TemporaryDirectory(prefix='ambi-controller-') as temporary:
    root = Path(temporary)
    project = root / 'rebuild'
    project.mkdir()
    for name in ('scene.rml', 'colours.rml'):
        shutil.copyfile(source / 'rebuild' / name, project / name)
    shutil.copytree(source / 'rebuild/assets', project / 'assets')
    shutil.copytree(source / 'ambi/assets', root / 'ambi/assets')
    artboards = {}
    for name in ('scene.rml', 'colours.rml'):
        for artboard in ET.parse(project / name).findall('Artboard'):
            artboards[artboard.get('name')] = artboard
    controller = ET.parse(source / 'ambi/controller.rml')
    for nested in controller.findall('.//NestedArtboard'):
        artboard = artboards[nested.get('name')]
        width, height = float(artboard.get('width')), float(artboard.get('height'))
        scale = min(340 / width, 240 / height)
        nested.set('artboardId', artboard.get('id'))
        nested.set('x', str((340 - width * scale) / 2))
        nested.set('y', str((240 - height * scale) / 2))
        nested.set('scaleX', str(scale))
        nested.set('scaleY', str(scale))
        nested.find('NestedStateMachine').set('animationId', artboard.get('defaultStateMachineId'))
    controller.write(project / 'controller.rml', encoding='unicode')
    (project / 'rive.yaml').write_text('name: ambi-character-controller\nmain: Ambi\n')
    subprocess.run([str(cli), str(project), '--verify'], check=True)
    subprocess.run([str(cli), str(project), '--once'], check=True)
    destination = Path(__file__).resolve().parents[1] / 'public/ambi.riv'
    shutil.copyfile(project / 'build/ambi-character-controller.riv', destination)
    print('Built v2 artwork with Ambi Controller:', destination)
