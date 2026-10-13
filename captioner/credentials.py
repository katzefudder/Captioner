"""
Content Credentials (C2PA) lesen, siehe docs/adr/0002-content-credentials.md.

Ein Bild kann ein Manifest eingebettet tragen (JPG, DNG, NEF, ARW, ...) oder als
Sidecar `<basis>.c2pa` daneben liegen. Gelesen wird ohne Netz (kein Abruf entfernter
Manifeste, kein OCSP). Ohne Vertrauensanker ist ein unversehrtes Manifest hoechstens
`Valid`; `Trusted` gibt es erst mit einer Vertrauensliste.

Wichtig fuers Schreiben: Jede Aenderung an einer Datei mit eingebettetem Manifest,
auch nur an XMP/IPTC, macht es ungueltig (`assertion.dataHash.mismatch`). Sidecars
(`.xmp`) neben einer RAW-Datei beruehren deren Manifest nicht. `at_risk()` nennt die
Dateien, die beim Speichern ihr Manifest verlieren wuerden.

Anzeige: `level()` (Farbe), `state_text()`, `action_text()`, `source_text()`;
Vergleich mit dem signierten Stand: `thumbnail()`, `difference()`, `metadata_changes()`.
"""
import contextlib
import io
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .i18n import _, N_

logger = logging.getLogger(__name__)

TRUSTED = 'Trusted'   # Signatur gueltig, Zertifikat auf der Vertrauensliste
VALID = 'Valid'       # Signatur und Hashes stimmen, Unterzeichner unbekannt
INVALID = 'Invalid'   # Datei oder Manifest nach dem Signieren veraendert, o. ae.

UNTRUSTED = 'signingCredential.untrusted'

# Stufen fuer Abzeichen und Filter (Galerie, Info-Panel)
LEVEL_TRUSTED, LEVEL_VALID, LEVEL_INVALID = 'trusted', 'valid', 'invalid'

ACTIONS = {
    'c2pa.created': N_('erstellt'),
    'c2pa.opened': N_('geöffnet'),
    'c2pa.placed': N_('eingefügt'),
    'c2pa.removed': N_('entfernt'),
    'c2pa.edited': N_('bearbeitet'),
    'c2pa.edited.metadata': N_('Metadaten bearbeitet'),
    'c2pa.color_adjustments': N_('Farbe angepasst'),
    'c2pa.cropped': N_('zugeschnitten'),
    'c2pa.drawing': N_('gezeichnet'),
    'c2pa.filtered': N_('Filter angewendet'),
    'c2pa.orientation': N_('gedreht/gespiegelt'),
    'c2pa.resized': N_('Größe geändert'),
    'c2pa.converted': N_('Format umgewandelt'),
    'c2pa.transcoded': N_('neu kodiert'),
    'c2pa.repackaged': N_('neu verpackt'),
    'c2pa.published': N_('veröffentlicht'),
    'c2pa.redacted': N_('geschwärzt'),
}

SOURCE_TYPES = {
    'digitalCapture': N_('Kamera-Aufnahme'),
    'computationalCapture': N_('Kamera-Aufnahme (berechnet)'),
    'negativeFilm': N_('Scan eines Negativs'),
    'positiveFilm': N_('Scan eines Dias'),
    'print': N_('Scan eines Abzugs'),
    'trainedAlgorithmicMedia': N_('KI-generiert'),
    'compositeWithTrainedAlgorithmicMedia': N_('mit KI-Anteilen'),
    'algorithmicallyEnhanced': N_('algorithmisch verbessert'),
    'algorithmicMedia': N_('algorithmisch erzeugt'),
    'composite': N_('Montage'),
    'compositeCapture': N_('Montage aus Aufnahmen'),
    'screenCapture': N_('Bildschirmfoto'),
    'digitalArt': N_('digitale Kunst'),
}

# Beschriftungsfelder (scanner.Metadata) und ihre Namen in Metadaten-Assertions
# (c2pa.metadata, aelter stds.iptc): XMP-Praefix oder IPTC-IIM-Name
METADATA_FIELDS = [
    ('headline', N_('Titel'), ('photoshop:Headline', 'Headline')),
    ('caption', N_('Beschreibung'), ('dc:description', 'Caption-Abstract')),
    ('keywords', N_('Tags'), ('dc:subject', 'Keywords')),
    ('city', N_('Stadt'), ('photoshop:City', 'City')),
    ('sublocation', N_('Ort'), ('Iptc4xmpCore:Location', 'Sub-location')),
    ('state', N_('Bundesland'), ('photoshop:State', 'Province-State')),
    ('country', N_('Land'), ('photoshop:Country', 'Country-PrimaryLocationName')),
    ('creator', N_('Fotograf'), ('dc:creator', 'By-line')),
    ('copyright', N_('Copyright'), ('dc:rights', 'CopyrightNotice')),
]
METADATA_ASSERTIONS = ('c2pa.metadata', 'stds.iptc', 'stds.iptc.photo-metadata')

# Nur lokal pruefen: Tests und Halle ohne Netz, und kein stilles Nachladen von Manifesten.
VERIFY = {'remote_manifest_fetch': False, 'ocsp_fetch': False}


@dataclass
class Step:
    """Ein Manifest der Kette: wer hat mit welchem Programm was getan."""
    generator: str = ''                            # z. B. "Captioner 0.1.0"
    signer: str = ''                               # CN des Zertifikats, sonst Aussteller
    issuer: str = ''                               # O des Zertifikats
    signed_at: str = ''                            # Zeitstempel (TSA), '' ohne
    actions: list = field(default_factory=list)    # ['c2pa.created', 'c2pa.edited.metadata']
    authors: list = field(default_factory=list)    # schema.org CreativeWork author
    title: str = ''
    source_type: str = ''                          # digitalSourceType ohne URL, z. B. 'digitalCapture'
    thumbnail: str = ''                            # JUMBF-URI des Vorschaubilds zu diesem Manifest
    metadata: dict = field(default_factory=dict)   # Feld (scanner.Metadata) -> Text beim Signieren


@dataclass
class Credentials:
    path: Path                                     # Bilddatei
    state: str = INVALID
    manifest: Path = None                          # Sidecar .c2pa; None = eingebettet
    failures: list = field(default_factory=list)   # Fehlercodes des aktiven Manifests
    history: list = field(default_factory=list)    # Step, neuestes zuerst
    remote_url: str = ''                           # verweist auf ein Manifest im Netz

    @property
    def active(self):
        return self.history[0] if self.history else Step()

    @property
    def embedded(self):
        return self.manifest is None

    @property
    def tampered(self):
        """Inhalt passt nicht mehr zur Signatur (nicht nur: Unterzeichner unbekannt)."""
        return any(code != UNTRUSTED for code in self.failures)

    @property
    def level(self):
        if self.tampered or self.state == INVALID:
            return LEVEL_INVALID
        return LEVEL_TRUSTED if self.state == TRUSTED else LEVEL_VALID


def level(found):
    """Stufe ueber alle Dateien eines Items: eine ungueltige zaehlt; None ohne Manifest."""
    if not found:
        return None
    levels = {credentials.level for credentials in found}
    for candidate in (LEVEL_INVALID, LEVEL_VALID):
        if candidate in levels:
            return candidate
    return LEVEL_TRUSTED


def state_text(credentials):
    if credentials.level == LEVEL_TRUSTED:
        return _('gültig, Unterzeichner vertrauenswürdig')
    if credentials.level == LEVEL_VALID:
        return _('gültig, Unterzeichner unbekannt')
    if any(code.endswith('.mismatch') for code in credentials.failures):
        return _('ungültig: Datei seit dem Signieren verändert')
    return _('ungültig')


def action_text(action):
    label = ACTIONS.get(action)
    return _(label) if label else action


def source_text(source_type):
    label = SOURCE_TYPES.get(source_type)
    return _(label) if label else source_type


def summary(found):
    """Eine Zeile je Datei, fuer Tooltips."""
    lines = []
    for credentials in found:
        signer = credentials.active.signer
        text = state_text(credentials) + (', ' + _('signiert von {signer}').format(signer=signer) if signer else '')
        lines.append(_('Content Credentials ({file}): {state}').format(file=credentials.path.name, state=text))
    return '\n'.join(lines)


def available():
    try:
        import c2pa  # noqa: F401
    except (ImportError, OSError):   # OSError: native Bibliothek laesst sich nicht laden
        return False
    return True


def sidecar_path(path):
    """Vorhandenes `<basis>.c2pa` (Schreibweise wie auf der Platte) oder None."""
    path = Path(path)
    wanted = path.stem.lower() + '.c2pa'
    try:
        names = os.listdir(path.parent)   # nicht exists(): macOS/Windows ignorieren die Schreibweise
    except OSError:
        return None
    return next((path.parent / name for name in names if name.lower() == wanted), None)


def _context(trust_anchors=None):
    import c2pa
    settings = {'verify': dict(VERIFY)}
    if trust_anchors:
        settings['trust'] = {'trust_anchors': trust_anchors}
    return c2pa.Context.from_dict(settings)


def read(path, trust_anchors=None):
    """Credentials der Datei (eingebettet, sonst Sidecar) oder None ohne Manifest.

    `trust_anchors`: PEM-Text der Wurzelzertifikate, denen vertraut wird.
    """
    import c2pa
    path = Path(path)
    context = _context(trust_anchors)
    manifest = None
    reader = c2pa.Reader.try_create(path, context=context)
    if reader is None:
        manifest = sidecar_path(path)
        if manifest is None:
            return None
        with open(path, 'rb') as stream:
            reader = c2pa.Reader(_mime(path), stream, manifest_data=manifest.read_bytes(),
                                 context=context)
            return _credentials(reader, path, manifest)
    with reader:
        return _credentials(reader, path, manifest)


def read_item(item, trust_anchors=None):
    """Credentials aller Dateien eines Items (RAW zuerst), nur die mit Manifest.

    Eine unlesbare Datei (kaputte RAW, fremdes Format) faellt nur selbst heraus.
    """
    import c2pa
    found = []
    for path in [item.raw, *item.embedded]:
        if path is None:
            continue
        try:
            credentials = read(path, trust_anchors)
        except (c2pa.C2paError, OSError) as e:
            logger.info('Content Credentials von %s nicht lesbar: %s', path.name, e)
            continue
        if credentials is not None:
            found.append(credentials)
    return found


def at_risk(item):
    """Dateien, deren noch unversehrtes eingebettetes Manifest beim Schreiben bricht.

    RAW-Dateien zaehlen nicht: dorthin schreibt Captioner nie, alles geht ins Sidecar.
    Ein schon ungueltiges Manifest auch nicht. Liest nach, falls der Scan noch nicht
    so weit ist (`item.credentials is None`).
    """
    if item.credentials is None:
        item.credentials = read_item(item) if available() else []
    embedded = set(item.embedded)
    return [c.path for c in item.credentials if c.embedded and c.path in embedded and not c.tampered]


@contextlib.contextmanager
def _reader(credentials):
    import c2pa
    context = _context()
    if credentials.manifest is None:
        with c2pa.Reader(credentials.path, context=context) as reader:
            yield reader
    else:
        with open(credentials.path, 'rb') as stream, \
                c2pa.Reader(_mime(credentials.path), stream, manifest_data=credentials.manifest.read_bytes(),
                            context=context) as reader:
            yield reader


def thumbnail(credentials, step):
    """Vorschaubild (JPEG/PNG-Bytes), wie es beim Signieren dieses Schritts aussah; None ohne."""
    if not step.thumbnail:
        return None
    import c2pa
    try:
        with _reader(credentials) as reader:
            stream = io.BytesIO()
            reader.resource_to_stream(step.thumbnail, stream)
            return stream.getvalue() or None
    except (c2pa.C2paError, OSError):
        return None


def difference(signed, current):
    """Differenzbild zweier Vorschauen (PIL-Bilder) und mittlere Abweichung 0..1.

    Grob: Vorschaugroesse, JPEG-Artefakte zaehlen mit. Taugt als Hinweis, wo sich etwas
    geaendert hat, nicht als Beweis.
    """
    from PIL import ImageChops, ImageOps
    signed = ImageOps.exif_transpose(signed).convert('RGB')
    current = ImageOps.exif_transpose(current).convert('RGB').resize(signed.size)
    diff = ImageChops.difference(signed, current)
    gray = diff.convert('L')
    score = sum(i * n for i, n in enumerate(gray.histogram())) / (255 * signed.width * signed.height)
    return diff.point(lambda value: min(255, value * 4)), score


def metadata_changes(step, meta):
    """[(Feldname, beim Signieren, jetzt, geaendert?)] fuer die Felder, die das Manifest kennt."""
    rows = []
    for name, label, _keys in METADATA_FIELDS:
        if name not in step.metadata:
            continue
        now = getattr(meta, name)
        now = ', '.join(now) if isinstance(now, list) else (now or '')
        then = step.metadata[name]
        rows.append((_(label), then, now, then.strip() != now.strip()))
    return rows


def _mime(path):
    suffix = Path(path).suffix.lower().lstrip('.')
    return {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'tif': 'image/tiff', 'tiff': 'image/tiff',
            'dng': 'image/dng', 'nef': 'image/x-nikon-nef', 'arw': 'image/x-sony-arw',
            'png': 'image/png', 'heic': 'image/heic', 'heif': 'image/heif'}.get(suffix, suffix)


def _credentials(reader, path, manifest):
    store = json.loads(reader.json())
    results = reader.get_validation_results() or {}
    # dict.fromkeys: gleiche Codes (z. B. zwei Hash-Bereiche) nur einmal, Reihenfolge bleibt
    failures = list(dict.fromkeys(entry.get('code', '')
                                  for entry in results.get('activeManifest', {}).get('failure', [])))
    return Credentials(
        path=path,
        state=reader.get_validation_state() or INVALID,
        manifest=manifest,
        failures=failures,
        history=history(store),
        remote_url=reader.get_remote_url() or '',
    )


def history(store):
    """Kette der Manifeste ueber die parentOf-Zutaten, neuestes zuerst."""
    manifests = store.get('manifests', {})
    steps, label, seen = [], store.get('active_manifest'), set()
    while label in manifests and label not in seen:
        seen.add(label)
        manifest = manifests[label]
        steps.append(_step(manifest))
        label = next((ingredient.get('active_manifest') for ingredient in manifest.get('ingredients', [])
                      if ingredient.get('relationship') == 'parentOf'), None)
    return steps


def _step(manifest):
    signature = manifest.get('signature_info') or {}
    actions, authors, source_type, metadata = [], [], '', {}
    for assertion in manifest.get('assertions', []):
        label, data = assertion.get('label', ''), assertion.get('data') or {}
        if label.startswith('c2pa.actions'):
            for action in data.get('actions', []):
                actions.append(action.get('action', ''))
                source_type = source_type or action.get('digitalSourceType', '').rsplit('/', 1)[-1]
        elif label == 'stds.schema-org.CreativeWork':
            authors += [author.get('name', '') for author in data.get('author', []) if author.get('name')]
        elif label in METADATA_ASSERTIONS:
            metadata.update(_metadata(data))
    return Step(
        generator=_generator(manifest),
        signer=signature.get('common_name') or signature.get('issuer', ''),
        issuer=signature.get('issuer', ''),
        signed_at=signature.get('time', ''),
        actions=actions,
        authors=authors,
        title=manifest.get('title', ''),
        source_type=source_type,
        thumbnail=(manifest.get('thumbnail') or {}).get('identifier', ''),
        metadata=metadata,
    )


def _metadata(data):
    found = {}
    for name, _label, keys in METADATA_FIELDS:
        for key in keys:
            if key in data:
                found[name] = _plain(data[key])
                break
    return found


def _plain(value):
    """XMP als JSON-LD: Text, Liste, Sprachvarianten {'x-default': ...} oder {'@value': ...}."""
    if isinstance(value, dict):
        for key in ('x-default', '@value', '@list'):
            if key in value:
                return _plain(value[key])
        return _plain(next(iter(value.values()), ''))
    if isinstance(value, list):
        return ', '.join(text for text in (_plain(v) for v in value) if text)
    return '' if value is None else str(value)


def _generator(manifest):
    info = manifest.get('claim_generator_info') or []
    if info:
        return ' '.join(part for part in (info[0].get('name', ''), info[0].get('version', '')) if part)
    return manifest.get('claim_generator', '')
