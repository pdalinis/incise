# Column alignment markers

Purpose: the delimiter row's `:` markers carry meaning and must survive every
operation — including sort, add-column, remove-column, and reorder-columns.

## All four forms

| Default | Left | Center | Right |
| ------- | :--- | :----: | ----: |
| a       | b    | c      | d     |
| e       | f    | g      | h     |

## Minimal delimiter widths

GFM permits a single dash. Re-padding must not silently expand these if the
table is ragged, and must expand them if the table is aligned.

|Left|Center|Right|
|:-|:-:|-:|
|1|2|3|

## Reorder hazard

Reordering columns must carry each column's alignment marker with it. Moving
`Right` to position 1 must move `----:` with it.
