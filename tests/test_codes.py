from captioner import codes


def test_resolve_replaces_codes(roster):
    result = codes.resolve('Zweikampf #bi99# gegen #bn23#', roster)
    assert result.ok
    assert result.text == 'Zweikampf -99- John Doe (Bietigheim Steelers) gegen -23- Marius Erk (EC Bad Nauheim)'
    assert result.persons == ['John Doe', 'Marius Erk']


def test_unknown_codes_are_kept_and_reported(roster):
    result = codes.resolve('Jubel #bi98# und #bi99#', roster)
    assert not result.ok
    assert result.unknown == ['bi98']
    assert '#bi98#' in result.text


def test_uppercase_code_falls_back_to_lowercase_entry(roster):
    # caps lock in the arena: #BN23# should still be resolved
    assert codes.resolve('#BN23#', roster).text == '-23- Marius Erk (EC Bad Nauheim)'


def test_custom_delimiter(roster):
    result = codes.resolve('Jubel \\bn31\\ #hashtag', roster, delimiter='\\')
    assert result.text == 'Jubel -31- Dean Döge (EC Bad Nauheim) #hashtag'


def test_coach_without_number_is_a_person(roster):
    assert codes.resolve('#bi100#', roster).persons == ['Tim Kehler']


def test_open_code_prefix():
    assert codes.open_code_prefix('Zweikampf #bi') == 'bi'
    assert codes.open_code_prefix('Zweikampf #') == ''
    assert codes.open_code_prefix('Zweikampf #bi99# gegen ') is None
    assert codes.open_code_prefix('Zweikampf #bi99# gegen #bn') == 'bn'
    assert codes.open_code_prefix('kein Code') is None


def test_persons_in_resolved_text(roster):
    text = 'Zweikampf -99- John Doe (Bietigheim Steelers) gegen -23- Marius Erk (EC Bad Nauheim)'
    assert codes.persons_in(text, roster) == ['John Doe', 'Marius Erk']
