# Aligned table

Purpose: pipes are padded to uniform column width. After any mutation, incise
must re-pad so the table stays aligned (§5.2, "match what the table already does").

## Components

| Component   | Status  | Owner   |
| ----------- | ------- | ------- |
| widget      | active  | peter   |
| widget-core | active  | dana    |
| gadget      | retired | rowan   |

Adding a row with a longer value than any existing cell forces every line of the
table to be rewritten. That is the one sanctioned exception to byte-preservation,
and only for the table's own lines.
