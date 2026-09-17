# Nested and mixed lists

Purpose: marker style and indentation width are per-list conventions that must
be detected and matched when inserting items, not normalized to a house style.

## Dash markers, two-space indent

- first
- second
  - second-a
  - second-b
    - second-b-i
- third

## Asterisk markers, four-space indent

* alpha
* beta
    * beta-one
    * beta-two
* gamma

## Plus markers

+ one
+ two

## Mixed markers at the same level

CommonMark treats a marker change as starting a *new list*. These are three
separate lists, not one list with three items.

- dash item

* star item

+ plus item

## Loose vs tight

Tight list, no blank lines between items:

- tight one
- tight two

Loose list, blank lines between items — renders with paragraph spacing, and
inserting an item must preserve the blank-line convention:

- loose one

- loose two

- loose three

## Multi-paragraph items

- An item whose content spans two paragraphs.

  This second paragraph belongs to the item above, indented to match.

- A simpler following item.

## Continuation lines

- An item with text that wraps onto a second source line without starting a
  new item, because it is indented under the marker.
- A normal item.
