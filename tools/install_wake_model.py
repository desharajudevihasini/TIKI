"""Install the small Vosk English model for TIKI's local 'spots on' wake phrase.

This fetches the publicly available language model once. No AI API credits.
"""
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'models' / 'vosk-model-small-en-us-0.15'
URL = 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'


def main():
    if (DEST / 'am' / 'final.mdl').exists():
        print('Wake word model already installed:', DEST)
        return
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tiki_vosk_') as tmp:
        archive = Path(tmp) / 'vosk.zip'
        print('Downloading Vosk offline English model (~40 MB)…')
        urllib.request.urlretrieve(URL, archive)
        print('Extracting wake model…')
        with zipfile.ZipFile(archive) as z:
            for file in z.infolist():
                p = Path(file.filename)
                if not p.parts or p.parts[0] != DEST.name or '..' in p.parts or p.is_absolute():
                    raise RuntimeError('Unexpected model ZIP structure')
            z.extractall(DEST.parent)
    if not (DEST / 'am' / 'final.mdl').exists():
        raise RuntimeError('Model installation incomplete; try again')
    print('Wake phrase ready: Hey TIKI, spots on')


if __name__ == '__main__':
    main()
