# CRLF line endings

Purpose: this file uses Windows CRLF line endings throughout. Every operation
must preserve them — reading with CRLF and writing back LF is a whole-file diff
and the single easiest way to destroy a document while "succeeding".

Newly inserted lines must also use CRLF, matching the file rather than the
platform incise happens to be running on.

## Components

| Component   | Status  | Owner |
| ----------- | ------- | ----- |
| widget      | active  | peter |
| widget-core | active  | dana  |

## Steps

1. first
2. second
3. third

## Mixed endings

A file with inconsistent endings is also possible in the wild. That case is
covered by `mixed-endings.md` rather than here, so this file stays uniformly
CRLF and the two behaviors can be tested independently.
