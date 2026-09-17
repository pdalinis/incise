# Task lists

Purpose: checkbox toggling, including nesting and the near-miss forms that are
not task items at all.

## Flat

- [ ] unchecked item
- [x] checked item
- [X] checked with capital X — must round-trip as capital X
- [ ] another unchecked

## Nested

- [ ] parent task
  - [x] child done
  - [ ] child pending
    - [ ] grandchild
- [x] sibling done

## Mixed with plain items

- [ ] a real task
- not a task, just an item
- [x] another real task
- [ordinary bracket text] also not a task

## Near misses

These look like task items but are not, per GFM:

- []  no space inside the brackets
- [ ]no space after the closing bracket
- [y] not a recognized marker

## Inside an ordered list

1. [ ] ordered task one
2. [x] ordered task two
