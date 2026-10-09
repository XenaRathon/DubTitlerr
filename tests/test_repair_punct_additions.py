"""Phase 22: with REPAIR_ACCEPT_PUNCT_CASE_ONLY=1 the relaxed path is for punctuation ADDITIONS only ('.' and ','), case changes
only on the lenient list, and a glossary spelling only when it is a real name. Synthetic pairs only (invented by a critic)."""

import pytest

import glossary
import repair

GL = glossary.load_dict(
    {
        "names": ["Luffy", "Law", "Rain", "Smoker", "Grand Line", "Devil Fruit", "Government", "Million Gold", "Monkey D. Luffy"],
        "phrases": ["Straw Hat Pirates"],
    }
)

# The critic's 60 meaning-changing pairs.
PAIRS = [
    ("Let's eat, Grandma.", "Let's eat Grandma."),
    ("Don't, stop!", "Don't stop!"),
    ("I like cooking, my family, and my pets.", "I like cooking my family and my pets."),
    ("Woman, without her man, is nothing.", "Woman: without her, man is nothing."),
    ("Look at that, man!", "Look at that man!"),
    ("Help, a thief!", "Help a thief!"),
    ("I resign, unfortunately.", "I resign unfortunately."),
    ("Slow, children playing.", "Slow children playing."),
    ("You're going to die.", "You're going to die?"),
    ("I am the king.", "I am the king?"),
    ("We won.", "We won?"),
    ("He did it.", "He did it?"),
    ("He's dead.", "He's dead?"),
    ("You want to fight.", "You want to fight?"),
    ("That is a bomb.", "That is a bomb?"),
    ('He said, "I am the boss".', '"He said I am the boss."'),
    ('"No," she cried.', 'No, "she cried."'),
    ('"I will kill you," he whispered.', "I will kill you, he whispered."),
    ('He is "smart".', "He is smart."),
    ('The "good" guys won.', "The good guys won."),
    ("I will kill...", "I will kill."),
    ("Wait... for me.", "Wait for me."),
    ("I think he is... dead.", "I think he is dead."),
    ("You... idiot!", "You idiot!"),
    ("Man-eating shark.", "Man eating shark."),
    ("Thirty-two year old.", "Thirty two-year-old."),
    ("Re-cover the sofa.", "Recover the sofa."),
    ("Co-op game.", "Coop game."),
    ("Extra-marital affairs.", "Extra marital affairs."),
    ("Small-business owner.", "Small business owner."),
    ("The boys' toys.", "The boys toys."),
    ("My parents' house.", "My parents house."),
    ("The dogs' bones.", "The dogs bones."),
    ("Jesus' words.", "Jesus words."),
    ("Workers' rights.", "Workers rights."),
    ("I love my apple.", "I love my Apple."),
    ("He went to the amazon.", "He went to the Amazon."),
    ("Look at the china.", "Look at the China."),
    ("I saw a turkey.", "I saw a Turkey."),
    ("We need more polish.", "We need more Polish."),
    ("Are you going to read?", "Are you going to Read?"),
    ("He is very frank.", "He is very Frank."),
    ("She is a daisy.", "She is a Daisy."),
    ("I have a bill to pay.", "I have a Bill to pay."),
    ("He wants to sue.", "He wants to Sue."),
    ("Give me a mark.", "Give me a Mark."),
    ("He has AIDS.", "He has aids."),
    ("I need a MAC.", "I need a mac."),
    ("Go to the ATM.", "Go to the atm."),
    ("I like it.", "i like it."),
    ("i am here.", "I am here."),
    ("STOP SHOUTING AT ME.", "stop shouting at me."),
    ("I WILL KILL YOU!", "i will kill you!"),
    ("the end of the world.", "The end of the world."),
    ("but I refused.", "But I refused."),
    ("1,000", "1.000"),
    ("3,14", "3.14"),
    ("[sighs] I'm tired.", "sighs I'm tired."),
    ("♪ Happy birthday to you ♪", "Happy birthday to you"),
    ("(crying) Please stop.", "crying Please stop."),
]

# The one pair on the list that phase 20's own leniency list allows on purpose: a lower-case pronoun 'i' at the start of a card
# that follows a finished sentence. Everything else must stay out of the relaxed path.
LENIENT_BY_DESIGN = {("i am here.", "I am here.")}


@pytest.fixture(autouse=True)
def flag(monkeypatch):
    monkeypatch.setenv("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "1")
    monkeypatch.setattr(glossary, "_ORDINARY", {"law", "rain", "smoker", "line", "government", "million", "turkey", "march"})


@pytest.mark.parametrize("orig,new", PAIRS)
def test_no_critic_pair_gets_the_relaxed_path(orig, new):
    if (orig, new) in LENIENT_BY_DESIGN:
        assert repair.is_punct_case_only(orig, new, GL, prev_text="Done.")
        return
    # A card start is lenient only after a finished sentence, so the two critic pairs that capitalise a card-initial word are
    # judged against a previous card that has not finished its sentence; every other pair against any previous card.
    prevs = (None, "He was saying") if orig[:1].islower() and orig[1:] == new[1:] else (None, "", "He left.", "He was saying")
    for prev in prevs:
        assert not repair.is_punct_case_only(orig, new, GL, prev_text=prev), prev


@pytest.mark.parametrize("orig,new", PAIRS)
@pytest.mark.parametrize("dur", [1.0, 6.0])
def test_with_the_flag_on_a_critic_pair_meets_exactly_the_ordinary_guards(orig, new, dur):
    if (orig, new) in LENIENT_BY_DESIGN:
        return
    on = repair.rejecting_guard(orig, new, "", dur, GL, punct_case_ok=True, prev_text="He was saying")
    off = repair.rejecting_guard(orig, new, "", dur, GL, punct_case_ok=False)
    assert on == off


# ---- what the relaxed path IS for: added '.' and ',' ----


@pytest.mark.parametrize(
    "orig,new",
    [
        ("we have to go", "We have to go."),
        ("Let's see what the cards say", "Let's see what the cards say."),
        (
            "it is just as bad as above once we surface we'll have one shot",
            "It is just as bad as above. Once we surface, we'll have one shot.",
        ),
        ("now according to his statement he is also a thief", "Now, according to his statement, he is also a thief."),
        ("Hello, world", "Hello, world."),
        ("Hello world?", "Hello, world?"),
        ("I'm sure you're searching for Kaido", "I'm sure you're searching for Kaido."),
    ],
)
def test_added_periods_and_commas_qualify(orig, new):
    assert repair.is_punct_case_only(orig, new, GL, prev_text="")


@pytest.mark.parametrize(
    "orig,new",
    [
        ("Hello world?", "Hello world."),  # '?' replaced
        ("Hello, world?", "Hello world?"),  # ',' removed
        ("Hello world", "Hello world!"),  # '!' is not an allowed addition
        ("Hello world", "Hello world?"),
        ("Hello world", "Hello; world"),
        ("Hello world", "Hello: world"),
        ("wait for me", "wait... for me"),  # an added ellipsis
        ("wait for me", "wait for me..."),
        ("wait for me", "wait for me…"),
        ("Hello world", 'Hello "world"'),
        ("Hello world", "Hello (world)"),
        ("man-eating", "man eating"),
        ("man eating", "man-eating"),
        ("[sighs]", "sighs"),
        ("1,000", "1.000"),
    ],
)
def test_anything_but_added_periods_and_commas_does_not(orig, new):
    assert not repair.is_punct_case_only(orig, new, GL, prev_text="")


def test_a_proposal_that_adds_a_comma_and_removes_a_question_mark_fails():
    assert not repair.is_punct_case_only("Are you coming?", "Are you, coming", GL, prev_text="")
    assert not repair.is_punct_case_only("Are you coming?", "Are you coming.", GL, prev_text="")
    assert repair.is_punct_case_only("Are you coming?", "Are you, coming?", GL, prev_text="")


def test_an_existing_ellipsis_may_stay_but_not_grow():
    assert repair.is_punct_case_only("wait... for me", "Wait... for me", GL, prev_text="")
    assert not repair.is_punct_case_only("wait.. for me", "wait... for me", GL, prev_text="")


def test_reorder_still_fails():
    assert not repair.is_punct_case_only("The dog bit the man.", "The man bit the dog.", GL, prev_text="")


# ---- the card's first word is a sentence start only after a finished sentence (reviewer item 3) ----


@pytest.mark.parametrize(
    "prev,lenient",
    [(None, False), ("", True), ("He arrived.", True), ("Really?", True), ("Stop!", True), ('He said "go."', True)]
    + [("He was saying", False), ("Wait...", False), ("Wait…", False), ("and then", False)],
)
def test_the_first_word_of_a_card_needs_a_finished_previous_card(prev, lenient):
    assert repair.is_punct_case_only("and then he left", "And then he left", GL, prev_text=prev) is lenient


def test_inside_a_card_a_sentence_end_between_the_words_is_enough():
    assert repair.is_punct_case_only("he left. we stayed", "he left. We stayed", GL, prev_text=None)
    assert repair.is_punct_case_only("who is it? they ran", "who is it? They ran", GL, prev_text=None)
    assert repair.is_punct_case_only("stop! now", "stop! Now", GL, prev_text=None)


@pytest.mark.parametrize("text", ["he left... we stayed", "he left… we stayed", "he left, we stayed", "he left we stayed"])
def test_an_ellipsis_or_comma_is_not_a_sentence_end(text):
    assert not repair.is_punct_case_only(text, text.replace("we", "We"), GL, prev_text="Done.")


def test_adding_the_period_and_the_capital_together_is_fine():
    assert repair.is_punct_case_only("he left we stayed", "he left. We stayed", GL, prev_text=None)


# ---- glossary spellings: real names only (reviewer item 2) ----


@pytest.mark.parametrize(
    "orig,new",
    [
        ("we met luffy today", "we met Luffy today"),  # a single-word entry that is not an ordinary word
        ("a devil fruit user", "a Devil Fruit user"),  # a whole multi-word entry, in sequence
        ("on the grand line", "on the Grand Line"),
        ("tell monkey d. luffy", "tell Monkey D. Luffy"),
        ("the straw hat pirates", "the Straw Hat Pirates"),
    ],
)
def test_a_real_name_is_lenient(orig, new):
    assert repair.is_punct_case_only(orig, new, GL, prev_text=None)


@pytest.mark.parametrize(
    "orig,new",
    [
        ("this is the law", "this is the Law"),  # an ordinary word that happens to be an entry
        ("we need rain", "we need Rain"),
        ("the smoker left", "the Smoker left"),
        ("a line formed", "a Line formed"),  # only a PART of 'Grand Line'
        ("the government fell", "the Government fell"),
        ("it costs 3.5 million", "it costs 3.5 Million"),  # only part of 'Million Gold'
        ("the devil in it", "the Devil in it"),  # one word of 'Devil Fruit'
        ("a devil fruit user", "a Devil fruit user"),  # the entry is not completed
        ("a devil fruit user", "a devil Fruit user"),
    ],
)
def test_an_ordinary_word_or_part_of_an_entry_is_not(orig, new):
    assert not repair.is_punct_case_only(orig, new, GL, prev_text=None)


# ---- end to end: prev_text reaches the gate ----


def test_rejecting_guard_takes_the_previous_card_text():
    dense = "and then he left"
    assert repair.rejecting_guard(dense, "And then he left", "", 6.0, GL, prev_text="He arrived.") is None
    assert repair.rejecting_guard(dense, "And then he left", "", 6.0, GL, prev_text="He arrived,") == "unchanged"
    assert repair.rejecting_guard(dense, "And then he left", "", 6.0, GL) == "unchanged"  # no previous-card information
