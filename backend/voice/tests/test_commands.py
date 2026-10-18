from commands import find_commands


def test_command_only_counts_right_after_the_wake_word():
    assert find_commands("Verity, accept.") == ["accept"]
    assert find_commands("verity clip and then verity up") == ["clip", "up"]
    assert find_commands("We're done here, I accept, go back up") == []
    assert find_commands("Verity is my sister's name. Done.") == []
    assert find_commands("verity") == []


def test_inflections_scribe_produces_still_match():
    assert find_commands("Verity accepts. Verity clipped. Verity confirmed.") == [
        "accept",
        "clip",
        "confirm",
    ]
    assert find_commands("verity upped downs") == []
