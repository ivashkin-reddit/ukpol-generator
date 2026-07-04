# ukpol-generator

Generate drop-in [r/ukpolitics](https://www.reddit.com/r/ukpolitics/) AutoModerator
social-media whitelist rules from the UK Parliament Members API.

Each generated rule mirrors the existing "Rule K-01 Whitelisted Twitter Accounts":
it reports (flags for moderator review) any link submission to a platform whose
account is **not** in the whitelist of known MP/Lord accounts. The output is a
separate drop-in file — it is never wired into `ukpolitics-automod.yaml`
automatically, and its `set_flair` values are deliberate placeholders.

## Architecture

The project uses a hexagonal (ports-and-adapters) layout under
[src/ukpol_generator](src/ukpol_generator):

| Layer | Responsibility |
| --- | --- |
| `domain/` | Pure logic: models, URL parsing, rule rendering (no I/O) |
| `ports/` | `Protocol` seams the application depends on |
| `adapters/` | Parliament API client, JSON cache store, YAML output writer |
| `application/` | Use-case services orchestrating the domain over ports |
| `cli.py` | Driving adapter wiring adapters to services |

## Usage

Fetch the raw member contacts (hits the network, caches to a JSON dump):

```shell
uv run ukpol-generator fetch --output mp_lords_contacts_raw.json
```

Generate the rules from the cached dump into `output/` (offline):

```shell
uv run ukpol-generator generate --input mp_lords_contacts_raw.json --output-dir output
```

Use `--filename` with `generate` or `run` to choose a different output filename:

```shell
uv run ukpol-generator generate --input mp_lords_contacts_raw.json --output-dir output --filename custom-social-rules.yaml
```

Do both in one step (fetch from the API, then generate):

```shell
uv run ukpol-generator run --output mp_lords_contacts_raw.json --output-dir output
```

The generated document is written to `output/generated-social-rules.yaml` by
default.

## Output Behaviour

The generator currently recognises Twitter/X, Facebook, Instagram, Bluesky,
LinkedIn, YouTube, TikTok, Threads, and known Mastodon instance hosts. Unknown
or non-profile URLs are skipped rather than guessed.

The cached contacts file is expected to be the JSON array written by `fetch`.
`generate` fails clearly if the cache root has the wrong shape, while individual
member records without an integer `id` are ignored.

URL parsing is intentionally conservative: only `http` and `https` profile URLs
are accepted, and TikTok, Threads, and Mastodon profiles must use an `@handle`
path. Generated inline comments are normalised so unusual API text cannot split
or reshape the YAML output.

## Development

```shell
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```
