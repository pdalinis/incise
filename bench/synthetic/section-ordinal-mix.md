# Alpha

## Notes

A leaf that repeats under one parent and also appears under another, which is
the one arrangement where the valid-ordinal list needs deduplicating.

Addressing `Notes` by its leaf matches three sections through the suffix pass.
Their full paths are `Alpha > Notes`, `Alpha > Notes` and `Beta > Notes`, so
the paths are not all distinct and the resolver treats the ordinal as the
addressing tool rather than pointing at a longer path. But the ordinals those
three carry are 0, 1 and **0** — the `Beta` one starts its own count — so the
list of valid ordinals has a repeat in it, and a refusal that prints
`ordinals 0, 1, 0` is telling the caller to send the same number twice.

`section-repeats.md` cannot reach this: its three `Notes` have three different
paths, so it exercises the ambiguity branch instead. `duplicate-siblings.md`
cannot either: its repeats all share one path, so their ordinals are 0, 1, 2
and never collide. The mix is what this file is for, and
`section-ordinal-dedup` survived a mutation run on exactly that gap.

## Notes

The second of the pair, ordinal 1.

# Beta

## Notes

The third, and ordinal 0 again — the count restarts because it is a different
path, which is the whole point of the fixture.
