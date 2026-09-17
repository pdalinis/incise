# HTML blocks

Purpose: raw HTML is passed through untouched. An HTML table is not a markdown
table and must not appear in `list-tables` output.

## HTML table

<table>
  <tr><th>Component</th><th>Status</th></tr>
  <tr><td>widget</td><td>active</td></tr>
</table>

## HTML heading

<h2>Not addressable as a markdown heading</h2>

Whether HTML headings appear in `outline` is a decision to make explicitly.
Excluding them is the simpler and probably correct answer.

## Details block containing markdown

GFM renders markdown inside `<details>` when separated by blank lines. So the
table below is a *real* markdown table nested in an HTML block — the hardest
case on this page.

<details>
<summary>Expand</summary>

| Name  | Value |
| ----- | ----- |
| alpha | 1     |
| beta  | 2     |

</details>

## Inline HTML

A paragraph with <strong>inline</strong> HTML and a <br> break. Editing text
around it must not disturb the tags.

## HTML comment

<!-- A comment containing | pipes | and a ## heading that must stay inert. -->

## Comment as an anchor

Some tools use comments as edit markers. If incise ever supports anchor
addressing, this is the shape it would take.

<!-- incise:begin components -->

| Component | Status |
| --------- | ------ |
| widget    | active |

<!-- incise:end components -->
