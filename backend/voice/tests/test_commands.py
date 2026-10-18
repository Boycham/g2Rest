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


def test_scribe_spells_queue_as_q():
    assert find_commands("Verity Q.") == ["queue"]
    assert find_commands("Verity, cue.") == ["queue"]
    assert find_commands("Q is my favourite letter.") == []


def test_verity_table_takes_the_number_in_digits_or_words():
    assert parse_commands("Verity, table four.") == [Command("table", table=4)]
    assert parse_commands("verity table 4") == [Command("table", table=4)]
    assert parse_commands("Verity table number 12.") == [Command("table", table=12)]
    assert parse_commands("Verity, table for.") == [Command("table", table=4)]
    assert parse_commands("Verity table. Verity accept.") == [Command("table"), Command("accept")]
    assert find_commands("A table for two, please.") == []


def test_tables_said_in_a_clip_skips_homophones():
    from commands import tables_said

    assert tables_said("The halibut, no butter. Thanks, that was table four.") == [4]
    assert tables_said("Table 2, sorry, table three.") == [2, 3]
    assert tables_said("Can we get a table for two by the window?") == []


# ---- sound-alikes: only right after a wake-word match ----

NEVER_FIRE = [
    "That was very tasty, thank you.",
    "Could you verify the bill for us?",
    "Can you verify done orders before you go?",
    "Verity is my sister's name, actually.",
    "We're done, I accept, let's go back up to the room.",
    "Could we get a table for two by the window?",
    "There's a variety of desserts tonight, all made in house.",
    "We have a variety menu on Sundays.",
    "There's variety up here and down there.",
    "Verily, this is the best halibut in town.",
    "The rarity of white truffles makes them pricey.",
    "We need some clarity on the menu, honestly.",
    "I'm very done with this traffic.",
    "Is this a charity dinner? Very good, I'll accept that.",
    "Every table here is booked, so there's a long queue.",
    "Except for the salmon, everything was great.",
    "Click the link and confirm your table.",
    "Very, very good. Done.",
    "Purity, parity and clarity.",
]


def test_conversation_never_fires_with_soundalikes_on():
    for phrase in NEVER_FIRE:
        assert parse_commands(phrase) == [], phrase


def test_misheard_wake_word_at_the_start_of_a_clause_before_a_command():
    assert find_commands("Verily, done.") == ["done"]
    assert find_commands("Variety, accept.") == ["accept"]
    assert find_commands("Okay, verety back.") == ["back"]
    assert find_commands("Varity menu.") == ["menu"]
    assert find_commands("Verty, confirm.") == ["confirm"]  # one edit from verity
    assert parse_commands("Verily, done.", soundalikes=False) == []


def test_misheard_wake_word_never_sends_unknown_words_to_gemini():
    assert parse_commands("Verily, give it to Ben.") == []
    assert parse_commands("Verity, give it to Ben.") == [Command("unknown", words="give it to ben")]


def test_misheard_command_words_after_the_wake_word():
    assert find_commands("Verity, except.") == ["accept"]
    assert find_commands("Verity conform.") == ["confirm"]
    assert find_commands("Verity click.") == ["clip"]
    assert find_commands("Verity, decleine.") == ["decline"]  # one edit, long word
    assert find_commands("Verity, revrt.") == ["revert"]
    assert find_commands("Verity, dome.") == []  # short words need an exact or listed form
    assert parse_commands("Verity, except.", soundalikes=False) == [
        Command("unknown", words="except")
    ]


def test_every_listed_soundalike_has_a_reason_and_maps_to_a_command():
    from commands import INTENTS, NOT_WAKE, SOUNDALIKES, WAKE_SOUNDALIKES, is_wake_soundalike

    assert all(reason for reason in WAKE_SOUNDALIKES.values())
    assert all(intent in INTENTS and reason for intent, reason in SOUNDALIKES.values())
    assert not any(is_wake_soundalike(w) for w in NOT_WAKE)


def test_keyterms_fit_the_realtime_limits():
    from commands import keyterms

    rt = keyterms()
    assert rt[0] == "Verity" and len(rt) <= 50 and all(len(k) <= 20 for k in rt)
    for must in ("done", "handoff", "exit", "Ava", "Ben", "Dana", "eight", "Burrata"):
        assert must in rt
    batch = keyterms(realtime=False)
    assert "Pan-Roasted Halibut" in batch and "halibut" in batch and len(batch) < 100


def test_a_sentence_about_someone_named_verity_is_not_an_unknown_command():
    for text in ("Verity is my sister's name.", "Verity was here earlier", "Verity said hi"):
        assert parse_commands(text) == [], text
    assert parse_commands("verity get the bill") == [Command("unknown", words="get the bill")]
