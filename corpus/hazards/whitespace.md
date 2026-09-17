# Whitespace quirks

Purpose: whitespace in markdown is sometimes semantic. This file has no trailing
newline at end of file, which is the last trap on the page.

## Hard line breaks

The line below ends with two spaces, which is a hard line break. Stripping  
trailing whitespace changes how this renders. Do not strip it.

A backslash at end of line is the other hard-break form.\
This line follows a backslash break.

## Tabs

The list below is indented with tab characters, not spaces.

- parent
	- tab-indented child
	- another tab-indented child

The table below uses tabs between cells:

| A	| B	|
| -	| -	|
| 1	| 2	|

## Blank line conventions

Some documents put two blank lines before each heading. Inserting a section
must match the surrounding convention rather than always emitting one.


## Heading after two blank lines


Body.


## Another heading after two blank lines

Body.

## Trailing spaces on a blank line

The "blank" line below actually contains three spaces.
   
That is still a blank line for parsing purposes, but it is not byte-identical
to an empty one, and must not be normalized.

## No trailing newline

This file ends without a final newline. Any operation must preserve that —
appending one is a real diff on a real line.