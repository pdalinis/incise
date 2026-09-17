# Ragged table

Purpose: pipes are not padded. After any mutation, incise must leave the table
ragged — it must NOT prettify. New rows adopt single-space cell padding.

## Components

|Component|Status|Owner|
|---|---|---|
|widget|active|peter|
|widget-core| active |dana|
|gadget|retired| rowan|

## Partially ragged

This one is *nearly* aligned but not quite. The rule is binary: a table is
"aligned" only if every row's pipes line up. This one does not qualify, so it is
treated as ragged and left alone.

| Name    | Value |
| ------- | ----- |
| alpha   | 1 |
| beta    | 22 |
| gamma | 333 |
