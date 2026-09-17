# Runs

## Two blank lines

Two blank lines end a list. What follows is a second list, not more of the
first, even when the marker and the indent match exactly.

- a
- b


- c
- d

## Indented four

A block indented four columns is code, and a line inside it that looks like a
list item is not one.

    - four spaces, so this is code
    - and so is this

Prose again, so the block above is closed.

## Indented six

Past four the same rule holds, and it is the *expanded* width that decides it:
a single tab is four columns.

      - six spaces
	- one tab

End.
