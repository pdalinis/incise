---
ingredient_tags: [one, two]
settings: {mode: fast, retries: 2}
quoted_sequence: "[one, two]"
quoted_mapping: '{mode: fast}'
nested:
  values: [three, four] # keep this comment
collections:
  - [alpha, beta]
  - {name: first}
---

# Flow collections

Purpose: distinguish opaque YAML flow collections from quoted scalar strings.
