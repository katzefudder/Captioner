"""Gemerkte Stichwoerter und Vorschlaege im Tag-Feld."""
from captioner import keywords


def test_history_keeps_recent_first_and_suggests(tmp_path):
    history = keywords.KeywordHistory(tmp_path / 'k.json')
    history.add(['Eishockey', 'DEL2', 'EC Bad Nauheim'], recent=False)
    history.add(['EC Kassel Huskies'])                 # zuletzt gespeichert: vorn
    history.add(['eishockey'])                         # gleiches Wort: nach vorn, nicht doppelt
    assert history.words == ['Eishockey', 'EC Kassel Huskies', 'DEL2', 'EC Bad Nauheim']
    assert history.suggestions('ec', exclude=['EC Kassel Huskies']) == ['EC Bad Nauheim']
    assert history.suggestions('huskies') == ['EC Kassel Huskies']   # auch mitten im Wort
    assert history.suggestions('e') == []                            # erst ab 2 Zeichen
    history.save()
    assert keywords.KeywordHistory(tmp_path / 'k.json').words == history.words


def test_current_token():
    text = 'Eishockey, DEL2,  EC Ka'
    assert keywords.current_token(text, len(text)) == (18, 'EC Ka')
    assert keywords.current_token('Eis', 3) == (0, 'Eis')
    assert keywords.current_token('a, b\nCo', 7) == (5, 'Co')
