import io
from pathlib import Path

import c2pa
import pytest

from captioner import credentials, scanner
from captioner.exiftool import ExifTool, find_exiftool
from conftest import make_jpeg, requires_exiftool

FIXTURES = Path(__file__).parent / 'fixtures' / 'c2pa'
CA = (FIXTURES / 'ca.pem').read_text()
CAPTURE = 'http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture'


def signer():
    info = c2pa.C2paSignerInfo(alg=b'es256', sign_cert=(FIXTURES / 'chain.pem').read_bytes(),
                               private_key=(FIXTURES / 'signer.key').read_bytes(), ta_url=None)
    return c2pa.Signer.from_info(info)


def manifest(*actions, author='Test Fotograf'):
    return {
        'claim_generator_info': [{'name': 'Captioner', 'version': '0.1.0'}],
        'assertions': [
            {'label': 'c2pa.actions', 'data': {'actions': [
                {'action': a, 'digitalSourceType': CAPTURE} if a == 'c2pa.created' else {'action': a}
                for a in actions]}},
            {'label': 'stds.schema-org.CreativeWork',
             'data': {'@context': 'https://schema.org', '@type': 'CreativeWork',
                      'author': [{'@type': 'Person', 'name': author}]}},
        ],
    }


def sign(source, dest, *actions, edit=False):
    with c2pa.Builder(manifest(*actions)) as builder:
        if edit:
            builder.set_intent(c2pa.C2paBuilderIntent.EDIT)   # Quelle wird zur parentOf-Zutat
        builder.sign_file(source, dest, signer())
    return dest


def test_no_manifest(tmp_path):
    assert credentials.read(make_jpeg(tmp_path / 'a.jpg')) is None


def test_embedded_manifest_is_valid_but_untrusted(tmp_path):
    path = sign(make_jpeg(tmp_path / 'raw.jpg'), tmp_path / 'a.jpg', 'c2pa.created')
    cred = credentials.read(path)
    assert cred.state == credentials.VALID
    assert cred.embedded and not cred.tampered
    assert cred.failures == [credentials.UNTRUSTED]
    assert cred.active.signer == 'Test Fotograf'
    assert cred.active.issuer == 'Captioner Tests'
    assert cred.active.generator == 'Captioner 0.1.0'
    assert cred.active.actions == ['c2pa.created']
    assert cred.active.authors == ['Test Fotograf']


def test_trusted_with_trust_anchor(tmp_path):
    path = sign(make_jpeg(tmp_path / 'raw.jpg'), tmp_path / 'a.jpg', 'c2pa.created')
    cred = credentials.read(path, trust_anchors=CA)
    assert cred.state == credentials.TRUSTED
    assert cred.failures == []


def test_history_follows_parent(tmp_path):
    first = sign(make_jpeg(tmp_path / 'raw.jpg'), tmp_path / 'first.jpg', 'c2pa.created')
    second = sign(first, tmp_path / 'second.jpg', 'c2pa.edited.metadata', edit=True)
    steps = credentials.read(second).history
    assert [s.actions for s in steps] == [['c2pa.opened', 'c2pa.edited.metadata'], ['c2pa.created']]


def test_sidecar_manifest(tmp_path):
    path = make_jpeg(tmp_path / 'a.jpg')
    with c2pa.Builder(manifest('c2pa.created')) as builder, open(path, 'rb') as source:
        builder.set_no_embed()
        data = builder.sign(signer(), 'image/jpeg', source, io.BytesIO())
    (tmp_path / 'a.C2PA').write_bytes(data)
    cred = credentials.read(path)
    assert cred.manifest == tmp_path / 'a.C2PA'
    assert cred.state == credentials.VALID


@requires_exiftool
def test_metadata_edit_breaks_embedded_manifest(tmp_path):
    """Grund fuer at_risk(): schon ein neuer Titel macht das Manifest ungueltig."""
    path = sign(make_jpeg(tmp_path / 'raw.jpg'), tmp_path / 'a.jpg', 'c2pa.created')
    item = scanner.Item(key='a', embedded=[path])
    assert credentials.at_risk(item) == [path]
    tool = ExifTool(find_exiftool()).start()
    try:
        tool.execute('-overwrite_original', '-IPTC:Headline=A - B gegen C', str(path))
    finally:
        tool.close()
    cred = credentials.read(path)
    assert cred.state == credentials.INVALID
    assert cred.tampered
    assert 'assertion.dataHash.mismatch' in cred.failures


def test_read_item_and_raw_not_at_risk(tmp_path):
    raw = sign(make_jpeg(tmp_path / 'x.jpg'), tmp_path / 'a.jpg', 'c2pa.created')
    item = scanner.Item(key='a', raw=raw, embedded=[make_jpeg(tmp_path / 'b.jpg')])
    assert [c.path for c in credentials.read_item(item)] == [raw]
    assert credentials.at_risk(item) == []


def test_level_and_texts(tmp_path):
    path = sign(make_jpeg(tmp_path / 'raw.jpg'), tmp_path / 'a.jpg', 'c2pa.created')
    cred = credentials.read(path)
    assert cred.level == credentials.LEVEL_VALID
    assert credentials.level([cred]) == credentials.LEVEL_VALID
    assert credentials.level([]) is None
    assert credentials.state_text(cred) == 'gültig, Unterzeichner unbekannt'
    assert credentials.action_text('c2pa.edited.metadata') == 'Metadaten bearbeitet'
    assert credentials.action_text('com.example.x') == 'com.example.x'
    assert cred.active.source_type == 'digitalCapture'
    assert credentials.source_text(cred.active.source_type) == 'Kamera-Aufnahme'
    assert 'a.jpg' in credentials.summary([cred])


def test_thumbnail_and_difference(tmp_path):
    from PIL import Image
    path = sign(make_jpeg(tmp_path / 'raw.jpg', color='blue'), tmp_path / 'a.jpg', 'c2pa.created')
    cred = credentials.read(path)
    data = credentials.thumbnail(cred, cred.active)
    assert data and Image.open(io.BytesIO(data)).size[0] > 0
    same = Image.open(io.BytesIO(data))
    _diff, score = credentials.difference(same, Image.open(path))
    assert score < 0.02
    _diff, score = credentials.difference(same, Image.new('RGB', (600, 400), 'yellow'))
    assert score > 0.3


@pytest.mark.parametrize('label', ['c2pa.metadata', 'stds.iptc'])
def test_metadata_changes(tmp_path, label):
    m = manifest('c2pa.created')
    m['assertions'].append({'label': label, 'data': {
        '@context': {'photoshop': 'http://ns.adobe.com/photoshop/1.0/', 'dc': 'http://purl.org/dc/elements/1.1/'},
        'photoshop:Headline': 'DEL - A gegen B', 'dc:description': {'x-default': 'Zweikampf'},
        'dc:subject': ['A', 'B']}})
    with c2pa.Builder(m) as builder:
        builder.sign_file(make_jpeg(tmp_path / 'raw.jpg'), tmp_path / 'a.jpg', signer())
    step = credentials.read(tmp_path / 'a.jpg').active
    assert step.metadata == {'headline': 'DEL - A gegen B', 'caption': 'Zweikampf', 'keywords': 'A, B'}
    rows = credentials.metadata_changes(step, scanner.Metadata(headline='DEL - A gegen B', caption='Torjubel',
                                                               keywords=['A', 'B']))
    assert rows == [('Titel', 'DEL - A gegen B', 'DEL - A gegen B', False),
                    ('Beschreibung', 'Zweikampf', 'Torjubel', True),
                    ('Tags', 'A, B', 'A, B', False)]


def test_at_risk_uses_loaded_credentials_and_skips_tampered(tmp_path):
    path = sign(make_jpeg(tmp_path / 'raw.jpg'), tmp_path / 'a.jpg', 'c2pa.created')
    item = scanner.Item(key='a', embedded=[path])
    assert credentials.at_risk(item) == [path]          # liest nach
    assert item.credentials[0].path == path
    item.credentials[0].failures.append('assertion.dataHash.mismatch')
    assert credentials.at_risk(item) == []              # schon gebrochen: nichts mehr zu schuetzen


@requires_exiftool
def test_protect_embedded_writes_only_the_sidecar(tmp_path):
    from captioner import metadata
    raw = tmp_path / 'DSC_0001.NEF'
    raw.write_bytes(b'raw')
    jpg = sign(make_jpeg(tmp_path / 'x.jpg'), tmp_path / 'DSC_0001.JPG', 'c2pa.created')
    item = next(i for i in scanner.scan(tmp_path) if i.raw)
    item.protect_embedded = True
    tool = ExifTool(find_exiftool()).start()
    try:
        written = metadata.write_item(tool, item, scanner.Metadata(headline='A - B gegen C', rating=3))
    finally:
        tool.close()
    assert [p.name for p in written] == ['DSC_0001.xmp']
    assert credentials.read(jpg).state == credentials.VALID
