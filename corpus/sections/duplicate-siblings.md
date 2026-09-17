# Duplicate sibling headings

Purpose: genuinely unresolvable addresses. Unlike `deep-nesting.md`, where a
full path disambiguates, these repeats share a parent — no path can separate
them. Every operation targeting them must fail with a candidate list including
ordinals, never silently pick the first.

## Notes

First Notes section.

## Notes

Second Notes section, same level, same parent, identical text.

## Notes

Third.

## Changelog

### 1.0

Release notes.

### 1.0

Duplicated by mistake — real documents do this, and mangling one of them
silently is the worst possible outcome.

## Trailing whitespace variants

The three headings below differ only in trailing whitespace and case. Whether
they count as duplicates is a decision the implementation must make explicitly.

### Setup

### Setup 

### setup
