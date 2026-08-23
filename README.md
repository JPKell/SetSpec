# SetSpec

Every versioned data contract that crosses an application boundary: benchmark results, capability evidence, event/error envelopes, prompt records.

**Status:** `0.1.0` — Phase 1 complete. The envelope, version negotiation and serialization core
are implemented and tested; the payload types they carry arrive in Phases 2 and 3, so
`SUPPORTED_SCHEMAS` is deliberately empty and a reader must pass the versions it accepts. See the
[development plan](docs/packages/setspec/development-plan.md) for what each phase adds.

Part of the **Local AI Suite** — see [docs/architecture/executive-summary.md](docs/architecture/executive-summary.md)
for how SetSpec fits with the suite's other applications and packages.

## Install

```bash
pip install setspec
```

## Quickstart

Write a document, then read it back:

```python
from setspec import GeneratorInfo, SchemaVersion, dump_envelope, load_envelope

generator = GeneratorInfo(name="freeweight", version="1.0.0")
document = dump_envelope(
    {"tokens_per_second": 42.0},
    schema="benchmark.result",
    version=SchemaVersion(1, 0),
    generator=generator,
)

envelope = load_envelope(document, expect="benchmark.result", supported=[SchemaVersion(1, 0)])
assert envelope.payload == {"tokens_per_second": 42.0}
```

`dump_envelope` returns canonical JSON: byte-identical for equal input, on every platform and
Python version, so a document can be hashed and diffed as well as read.

Payload types come in two halves generated from one definition — a strict `Out` for writers and a
preserving `In` for readers ([ADR-0009 rule 4](docs/adr/0009-setspec-schema-strategy.md)):

```python
from setspec import PayloadDefinition, payload_models
from setspec.serialization import MeasurementField


class ResultFields(PayloadDefinition):
    reading: MeasurementField
    unit: str


ResultOut, ResultIn = payload_models(ResultFields)

# A reader keeps what a newer writer added, so a re-export loses nothing.
received = ResultIn.model_validate({"reading": 1.5, "unit": "ms", "confidence": 0.87})
assert received.extras == {"confidence": 0.87}
```

A measurement this environment cannot provide is `UNSUPPORTED`, which serializes as the string
`"unsupported"` — never `null`, never `0`
([ADR-0016](docs/adr/0016-unavailable-is-not-zero.md)).

See [docs/packages/setspec/spec.md](docs/packages/setspec/spec.md) §7 for the full public API and
§20 for the acceptance criteria.

## Documentation

This repository carries its own copy of the relevant suite documentation under [`docs/`](docs/README.md),
so it can be read and implemented independently of the other eight suite repositories. Start with
[`docs/README.md`](docs/README.md).

| Read this | For |
|---|---|
| [docs/packages/setspec/spec.md](docs/packages/setspec/spec.md) | Purpose, scope, non-goals, public contracts, configuration, acceptance criteria |
| [docs/packages/setspec/development-plan.md](docs/packages/setspec/development-plan.md) | The phased build plan: goals, work, tests, acceptance criteria per phase |
| [docs/standards/](docs/standards/) | Coding, testing, security, API, database and packaging standards every phase follows |
| [docs/adr/](docs/adr/README.md) | The architectural decisions this design rests on |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
pytest -m "not live and not performance"
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full workflow and [`SECURITY.md`](SECURITY.md) for
how to report a vulnerability.

## License

Apache-2.0 — see [`LICENSE`](LICENSE).
