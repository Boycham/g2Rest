from commands import Command, find_commands, parse_commands


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


def test_realtime_spelling_of_done():
    assert find_commands("Verity Dunn.") == ["done"]


def test_handoff_with_and_without_a_name():
    assert parse_commands("Verity, handoff.") == [Command("handoff")]
    assert parse_commands("Verity hand off to Maya.") == [Command("handoff", name="Maya")]
    assert parse_commands("Verity handoff Ben. Thanks.") == [Command("handoff", name="Ben")]
    assert find_commands("I'll hand off the bread.") == []


def test_nevermind_and_revert():
    assert find_commands("Verity, never mind.") == ["nevermind"]
    assert find_commands("Verity nevermind.") == ["nevermind"]
    assert find_commands("Verity, revert.") == ["revert"]


def test_short_unknown_words_after_the_wake_word_go_to_gemini():
    assert parse_commands("Verity, give it to Ben.") == [Command("unknown", words="give it to ben")]
    assert parse_commands("Verity, um. We'll have the soup.") == [Command("unknown", words="um")]


def test_long_talk_after_the_wake_word_is_not_a_command():
    assert parse_commands("Verity is my sister's name and she loves the halibut here.") == []
    assert parse_commands("Thanks, Verity.") == []


def test_menu_controls_and_queue():
    assert find_commands("Verity menu. Verity controls. Verity, queue.") == [
        "menu",
        "menu",
        "queue",
    ]
    assert find_commands("Is there a queue for the menu?") == []
