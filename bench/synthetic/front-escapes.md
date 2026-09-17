---
escaped: "a \" b" # a comment after an escaped quote
hidden: "a \" # not a comment"
doubled: "back\\slash" # a comment after a doubled backslash
trailing: "ends with \\" # a comment after a value ending in a backslash
single_bs: 'a \' # the backslash is literal inside single quotes
sq_hash: 'it''s # not a comment'
plain: bare value # an ordinary comment
---

# Escapes

The values above are the ones where the comment scanner's quote tracking and
its backslash rule disagree about where the value ends.
