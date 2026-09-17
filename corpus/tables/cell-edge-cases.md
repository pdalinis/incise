# Table cell edge cases

Purpose: the cases that break naive pipe-splitting. Any operation on this table
must round-trip every cell exactly.

## Hazardous cells

| Case            | Value                    | Note                       |
| --------------- | ------------------------ | -------------------------- |
| escaped pipe    | a \| b                   | literal pipe, backslashed  |
| code with pipe  | `cmd \| grep`            | pipe in code span, escaped |
| empty cell      |                          | cell is empty, not missing |
| link            | [docs](https://ex.com/a) | brackets and parens        |
| bold + italic   | **bold** and _italic_    | inline emphasis            |
| trailing spaces | padded                   | source has trailing space  |
| backslash       | C:\\path\\to             | literal backslashes        |
| CJK width       | 日本語テキスト           | 2 columns wide per glyph   |
| emoji           | 🚀 ship it               | multi-codepoint grapheme   |
| html entity     | &amp; &lt;               | must not be decoded        |

## Ragged cell counts

GFM pads short rows and truncates long ones. incise must decide explicitly:
normalize to the header's column count, or fail loudly. It must not silently
drop the extra cell.

| A | B | C |
| - | - | - |
| 1 | 2 |
| 1 | 2 | 3 | 4 |

## Single column

| Only |
| ---- |
| one  |
