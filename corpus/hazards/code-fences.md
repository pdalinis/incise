# Code fences

Purpose: everything below that *looks* structural is inert. A parser that
locates tables or headings by regex will corrupt this file. `table-get` here
must report zero tables, and `outline` must report only the real headings on
this page.

## Fenced table

```
| Component | Status |
| --------- | ------ |
| fake      | inert  |
```

## Fenced headings and lists

```markdown
# Not a real heading
## Also not real

- not a real list item
- [ ] not a real task

---
title: not real frontmatter
---
```

## Tilde fences

~~~
| Also | Inert |
| ---- | ----- |
| a    | b     |
~~~

## Nested fences

A four-backtick fence containing a three-backtick fence. Naive fence matching
will terminate at the wrong place and treat the rest of the file as code.

````markdown
```
| Inner | Table |
| ----- | ----- |
| still | inert |
```
````

## Indented code block

Four spaces of indentation, no fence:

    | Indented | Table |
    | -------- | ----- |
    | inert    | too   |

    ## Indented heading, also inert

## Unclosed fence

The fence below is deliberately never closed. Everything after it is code
through end of file, so the "heading" and "table" that follow are inert. If the
implementation instead recovers by treating it as text, that is a defensible
choice — but it must be a deliberate, documented one.

```
## Trailing heading inside an unclosed fence

| Trailing | Table |
| -------- | ----- |
| inert    | ?     |
