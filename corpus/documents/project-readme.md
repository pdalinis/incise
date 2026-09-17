# acmectl

[![build](https://img.shields.io/badge/build-passing-green)](https://ci.example.com)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Purpose in the corpus: a realistic project README — the single most common
document an agent is asked to edit. Mixes tables, lists, fenced code, links,
badges, and prose in the proportions found in the wild.

Representative benchmark tasks against this file:

- add a row to the **Supported platforms** table, keeping it sorted
- mark a row in **Feature status** as `stable`
- add a bullet to **Requirements** in alphabetical position
- bump the version in the install snippet without touching adjacent lines

## Requirements

- Go 1.21 or newer
- Make
- A POSIX shell
- Docker (optional, for integration tests)

## Install

```bash
curl -fsSL https://get.example.com/acmectl/v1.4.2 | sh
```

Or with Homebrew:

```bash
brew install acme/tap/acmectl
```

## Supported platforms

| Platform | Arch    | Status    | Since |
| -------- | ------- | --------- | ----- |
| Linux    | amd64   | supported | 0.1.0 |
| Linux    | arm64   | supported | 0.9.0 |
| macOS    | arm64   | supported | 1.0.0 |
| macOS    | amd64   | supported | 0.4.0 |
| Windows  | amd64   | beta      | 1.3.0 |
| FreeBSD  | amd64   | community | 1.1.0 |

Note the composite key: neither `Platform` nor `Arch` alone identifies a row.
Row addressing must support multiple predicates.

## Feature status

| Feature        | Status       | Tracking issue                              |
| -------------- | ------------ | ------------------------------------------- |
| `sync`         | stable       | —                                           |
| `watch`        | stable       | —                                           |
| `plan`         | beta         | [#412](https://github.com/acme/ctl/issues/412) |
| `apply --diff` | experimental | [#588](https://github.com/acme/ctl/issues/588) |
| `remote`       | planned      | [#601](https://github.com/acme/ctl/issues/601) |

## Usage

```
acmectl [command] [flags]

Commands:
  sync     Reconcile local state with remote
  plan     Preview changes without applying
  apply    Apply pending changes
  version  Print version and exit
```

### Flags

| Flag        | Type   | Default | Description                    |
| ----------- | ------ | ------- | ------------------------------ |
| `--config`  | path   | `.acme` | Config file location           |
| `--verbose` | bool   | `false` | Verbose logging                |
| `--timeout` | int    | `30`    | Request timeout in seconds     |
| `--dry-run` | bool   | `false` | Print actions without applying |

## Configuration

Config is read from `.acme/config.yaml`:

```yaml
remote: https://api.example.com
timeout: 30
features:
  - sync
  - plan
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for your change
4. Run `make check`
5. Open a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

## Maintainers

| Name  | Area          | Timezone |
| ----- | ------------- | -------- |
| Peter | core, CLI     | UTC-8    |
| Dana  | remote sync   | UTC+1    |
| Rowan | docs, release | UTC+10   |

## License

MIT — see [LICENSE](LICENSE).
