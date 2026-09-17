---
---

# Empty frontmatter

Purpose: the delimiters are present but the block has no keys. This is distinct
from `absent.md` and both must be distinguishable by `frontmatter-get`.

Setting a key here must fill the existing block rather than creating a second
one. Deleting the last key must leave the empty block intact rather than
removing the delimiters — removing them is a structural change the caller did
not request.
