"""Add the supplied Ambi controller to the v2 source pack using Rive CLI 1.8.0.
Usage: python3 ui/scripts/build-rive-controller.py SOURCE_PACK RIVE_CLI
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
parser.add_argument('cli', type=Path)
parser.add_argument('--transparent', action='store_true', help='Remove only artboard background fills')
parser.add_argument('--output', type=Path)
args = parser.parse_args()
source, cli = args.source.resolve(), args.cli.resolve()
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
        tree = ET.parse(project / name)
        for artboard in tree.findall('Artboard'):
            if args.transparent:
                for fill in artboard.findall('Fill'):
                    artboard.remove(fill)
            artboards[artboard.get('name')] = artboard
        tree.write(project / name, encoding='unicode')
    controller = ET.parse(source / 'ambi/controller.rml')
    if args.transparent:
        for artboard in controller.findall('Artboard'):
            for fill in artboard.findall('Fill'):
                artboard.remove(fill)
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
    destination = args.output or Path(__file__).resolve().parents[1] / 'public/ambi.riv'
    shutil.copyfile(project / 'build/ambi-character-controller.riv', destination)
    print('Built v2 artwork with Ambi Controller:', destination)
