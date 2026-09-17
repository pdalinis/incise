# Nested block structures

Purpose: tables and lists that are not top-level. Addressing must reach them or
fail loudly — the unacceptable outcome is reporting "not found" for a table
that is plainly present, or editing it and destroying the enclosing indentation.

## Table inside a list item

- First step, with a table of options:

  | Flag      | Default |
  | --------- | ------- |
  | `--force` | false   |
  | `--quiet` | false   |

- Second step, no table.

## Table inside a blockquote

> Quoted context.
>
> | Name | Value |
> | ---- | ----- |
> | a    | 1     |
> | b    | 2     |
>
> Trailing quoted text.

Adding a row here must emit the `> ` prefix. Forgetting it silently breaks the
row out of the blockquote.

## List inside a blockquote

> - quoted item one
> - quoted item two
>   - quoted nested item

## Nested blockquote

> outer
> > inner
> > - item in a doubly-quoted list

## List inside a table cell

Not expressible in GFM — a `<br>` is the usual workaround. Included so the
implementation does not attempt to parse it as a list.

| Item  | Sub-items          |
| ----- | ------------------ |
| alpha | one<br>two<br>three |

## Heading inside a blockquote

> ## Quoted heading
>
> Body of the quoted section.

Whether this appears in `outline` is a decision to make explicitly.
