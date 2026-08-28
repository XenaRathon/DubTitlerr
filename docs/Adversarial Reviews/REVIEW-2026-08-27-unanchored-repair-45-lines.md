# Unanchored repair - 45 lines for review

One Pace S31E01-E03, 45 repairs from 393 targets, on the real code at 5616ca7
with both [S-14] and [S-15] guards active. nanbeige4.2-3b. No card here has a
fansub anchor, so none of these would be repaired at all today, and none can be
repaired by anything downstream if a regression ships.

The spec makes this read a REQUIRED step before an episode is accepted: the bar is
referent and sense, not word-for-word, and nothing mechanical checks meaning.
Known from the earlier E01 pass: factory -> needle and VIVRA -> Vivi are
regressions; Mihawk shortened from Hawkeye Dracule Mihawk is acceptable by owner
call. Everything else is unjudged.

## S31E01

- [x] ASR : That come together.
      FIX : That comes together.
- [x] ASR : Roger's treasure belongs to me
      FIX : Roger's treasure belongs to me.
- [x] ASR : We'll ride non-stop and travel farther
      FIX : We'll ride non-stop and travel farther.
- [x] ASR : That's right, we're shining,
      FIX : That's right, we're shining.
- [x] ASR : running forever Let's go along with curiosity Our feelings lead
      FIX : Running forever. Let's go along with curiosity. Our feelings lead.
- [x] ASR : I've been trying to call the bastards all day,
      FIX : I've been trying to call the bastards all day.
- [x] ASR : We're gonna die, that's what.
      FIX : We're gonna die. That's what.
- [x] ASR : It's the other news that troubles me,
      FIX : It's the other news that troubles me.
- [x] ASR : your crew disappeared for two years What were you doing all that time?
      FIX : Your crew disappeared for two years. What were you doing all that time?
- [ ] ASR : We're looking for a factory.
      FIX : We're looking for a needle.
- [x] ASR : once we get there we'll find it super easy my lasers will take
      FIX : Once we get there we'll find it super easy. My lasers will take
- [x] ASR : we might need to think outside the box we're going to Greenbit
      FIX : We might need to think outside the box. We're going to Greenbit.
- [x] ASR : I relied on the brave assistance of my fellow Samadai,
      FIX : I relied on the brave assistance of my fellow Samurai.
- [ ] ASR : Spare Mata-koth for me!
      FIX : Sparing Mata-koth for me!
- [x] ASR : First, the world's greatest swordsman, Hawkeye Dracule Mihawk.
      FIX : First, the world's greatest swordsman, Mihawk.
- [x] ASR : The heavenly demon, Don Quixote Dothamingo.
      FIX : The heavenly demon, Don Quixote Doflamingo.
- [x] ASR : I shall be the shogun of Wano someday And you'll be in the war beneath my face!
      FIX : I shall be the shogun of Wano someday. You'll be in the war beneath my face!
- [ ] ASR : It's a VIVRA card?
      FIX : It's a Vivi card?
- [x] ASR : I'm over it now come on let's eat
      FIX : I'm over it now. Come on, let's eat.
- [x] ASR : This is no good at all Give up, you had enough, old man.
      FIX : This is no good at all. Give up, you had enough, old man.
- [x] ASR : We run this joint you got that they left me no
      FIX : We run this joint. You got that? They left me no...

## S31E02

- [x] ASR : That come together.
      FIX : That comes together.
- [x] ASR : Roger's treasure belongs to me
      FIX : Roger's treasure belongs to me.
- [x] ASR : We'll ride non-stop and travel farther
      FIX : We'll ride non-stop and travel farther.
- [x] ASR : That's right, we're shining,
      FIX : That's right, we're shining.
- [x] ASR : running forever Let's go along with curiosity Our feelings lead
      FIX : Running forever. Let's go along with curiosity. Our feelings lead.
- [x] ASR : our moths will never give up There's a fire in our dreams and you can never,
      FIX : Our moths will never give up. There's a fire in our dreams and you can never,
- [x] ASR : My shoes was right here a minute ago! What?!
      FIX : My shoes were right here a minute ago! What?!
- [x] ASR : Senor Pink, then Dellinger,
      FIX : Senor Pink, then Dellinger.
- [x] ASR : and of course, the Colosseum's reigning
      FIX : and of course, the Colosseum's reigning.

## S31E03

- [x] ASR : My darkness will swallow the world, just you wait and see.
      FIX : My darkness will swallow the world. Just you wait and see.
- [x] ASR : Roger's treasure belongs to me
      FIX : Roger's treasure belongs to me.
- [x] ASR : We'll ride non-stop and travel farther
      FIX : We'll ride non-stop and travel farther.
- [x] ASR : That's right, we're shining,
      FIX : That's right, we're shining.
- [x] ASR : running forever Let's go along with curiosity Our feelings lead
      FIX : Running forever. Let's go along with curiosity. Our feelings lead.
- [x] ASR : running forever Open the map inside your heart and see No matter where we end up,
      FIX : Running forever. Open the map inside your heart and see. No matter where we end up,
- [x] ASR : our moths will never give up There's a fire in our dreams And you can never,
      FIX : Our moths will never give up. There's a fire in our dreams and you can never,
- [x] ASR : They don't believe it—that's Cyan Boo from Kano,
      FIX : They don't believe it—that's Cyan Boo from Kano.
- [x] ASR : and that's not Chin Down behind them.
      FIX : That's not Chin Down behind them.
- [x] ASR : armor helmets and swords my head's about to
      FIX : Armor helmets and swords, my head's about to
- [x] ASR : There's only one who deserves the flame flame fruit.
      FIX : There's only one who deserves the Flame-Flame Fruit.
- [x] ASR : It's the most mysterious statue in Dres Rosa.
      FIX : It's the most mysterious statue in Dressrosa.
- [x] ASR : It'll be big trouble if one of these guys wins the flame flame fruit.
      FIX : It'll be big trouble if one of these guys wins the Flame-Flame Fruit.
- [ ] ASR : CP-0.
      FIX : CP?
- [x] ASR : Do it again, Choppa Amon!
      FIX : Do it again, Chopper Amon!

## Verdict — owner read, 2026-08-27

41 of 45 accepted, 4 rejected. Five of the 41 needed a hand-correction, so the
rate that passed untouched is 36/45.

Rejected:

- `We're looking for a factory.` -> `a needle.` — semantic substitution (known).
- `It's a VIVRA card?` -> `a Vivi card?` — item swapped for a character (known).
- `Spare Mata-koth for me!` -> `Sparing Mata-koth for me!` — imperative turned gerund.
- `CP-0.` -> `CP?` — a canonical organisation name destroyed.

Hand-corrected inside the accepted set, in three classes:

- WORD DELETION (2x): `the flame flame fruit` -> model `the flame fruit`, owner
  `the Flame-Flame Fruit`. Ratio 0.88 against a 0.6-1.5 band, shorter so `fits_card`
  passes, no reference to borrow from, no new token for `invents_name` to see.
  `accept_repair` cannot detect this. It is the same class as factory -> needle and
  was caught only because the owner knew the term.
- TRAILING PERIOD ON A CONTINUATION CARD (2x): `My lasers will take.` and
  `my head's about to.`, both mid-sentence spillovers. One character, invisible to
  every gate.
- UNDER-REPAIR (1x): `my fellow Samadai` got a period and not the fix; owner supplied
  `Samurai`.

## Two bars, not one — owner, 2026-08-28

The Mihawk line records BOTH verdicts and they do not contradict each other. Read in this
document it was "acceptable by owner call"; reviewed line-by-line on the review page the
owner rejected it. The bar moved because the context did:

- **Automated pipeline**: acceptable. `Hawkeye Dracule Mihawk` -> `Mihawk` keeps the
  referent, the scene plays, and holding the whole run for it would cost more than it buys.
- **Human review**: rejected. "If I'm reviewing it myself I'm going to try to get it as
  perfect as my ears allow." A reviewer already watching the card is not choosing between
  the repair and nothing; they are choosing between the repair and the right line.

This matters for the tightening this document exists to feed. A `reject` recorded on the
review page is NOT automatically evidence that `accept_repair` should have blocked the
repair — some of them are the higher bar being applied, not the guard being wrong.
Calibrating the guard against every human rejection would tighten it to a standard only the
manual pass ever applies, and the cost lands on the unattended runs that have no reviewer.
When that pass happens, the review verdicts need splitting into "the guard missed a
regression" and "a human could do better here" before any threshold moves.

Owner's decision on the failures: `accept_repair` is NOT to be tightened now. The
current version is acceptable at this stage, and the tightening waits for more
human-reviewed data. Each stage of the build is about getting closer to the goal,
not chasing perfection early. The six failures are recorded here as the input for
that later pass, not as a spec to act on yet.
