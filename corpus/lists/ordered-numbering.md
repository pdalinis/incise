# Ordered list numbering

Purpose: inserting into an ordered list requires deciding whether to renumber
the following items. The right answer depends on the list's existing style.

## Sequential

Inserting between 2 and 3 requires renumbering 3 and 4.

1. first
2. second
3. third
4. fourth

## All ones

A legal and common style — the renderer numbers them. Inserting requires no
renumbering at all, and renumbering would be wrong.

1. first
1. second
1. third

## Paren delimiter

Marker style is `)` not `.` and must be matched by inserted items.

1) first
2) second
3) third

## Non-one start

CommonMark honors the first number as the start value. Inserting at the front
changes the start value; inserting elsewhere does not.

5. five
6. six
7. seven

## Non-sequential

Already inconsistent in the source. Renumbering it is a behavior change the
caller did not ask for.

1. first
3. third
7. seventh

## Nested under unordered

- context item
  1. nested first
  2. nested second
- following item
