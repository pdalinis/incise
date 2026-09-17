# Multiple tables per section

Purpose: heading path alone is an ambiguous table address here. Exercises
ordinal addressing (`--table 2`) and the ambiguity error that must list
candidates rather than guessing.

## Environments

Production hosts:

| Host  | Region    | Size |
| ----- | --------- | ---- |
| web-1 | us-east-1 | m5.l |
| web-2 | us-east-1 | m5.l |

Staging hosts:

| Host    | Region    | Size |
| ------- | --------- | ---- |
| stage-1 | us-west-2 | t3.m |

Scratch hosts:

| Host      | Region    | Size |
| --------- | --------- | ---- |
| scratch-1 | us-west-2 | t3.s |

## Networks

Only one table here, so the heading path is sufficient and no ordinal is needed.

| CIDR         | Purpose |
| ------------ | ------- |
| 10.0.0.0/16  | private |
| 10.1.0.0/16  | public  |
