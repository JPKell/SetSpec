"""Contract module — the errors SetSpec raises across a package boundary.

Imports pydantic but performs no I/O. Every error here derives from
:class:`baseaicore.SuiteError`, so a caller that already handles suite errors handles these too,
and every ``code`` is part of the public contract
([spec §13](../../docs/packages/setspec/spec.md)): adding a code is a minor change, changing what
one means is a major one.

Two error types reach callers of this package, and the split is deliberate:

* :class:`SchemaVersionUnsupported` — the payload is well-formed but this build cannot read its
  major version. It is a *negotiation* outcome, not a defect in the data, and consumers branch on
  it to fall back or to tell the user to upgrade.
* :class:`~baseaicore.ValidationError` — the payload is malformed, oversized, too deeply nested, or
  structurally wrong. Re-exported here so callers import both from one place.

Pydantic's own ``ValidationError`` is deliberately **not** part of this package's contract at the
envelope boundary. :func:`~setspec.envelope.load_envelope` converts it, preserving every offending
field path in ``details["errors"]`` — so a caller gets one error type and still learns everything
that was wrong at once (spec §13). Constructing a payload model directly is ordinary pydantic use
and raises pydantic's error, as a pydantic user expects.
"""

from __future__ import annotations

from typing import Any, ClassVar

from baseaicore import SuiteError, ValidationError

__all__ = [
    "SchemaVersionUnsupported",
    "ValidationError",
]


class SchemaVersionUnsupported(SuiteError):
    """A payload declares a schema major version this build cannot read.

    Raised only for an unsupported **major**. A newer *minor* within a supported major is accepted
    by design — that is the reader policy in
    ADR-0009 rule 3, and it is what lets two
    applications at different versions exchange documents. An unsupported major is never partially
    parsed: a breaking change means the fields no longer mean what this build thinks they mean, so
    reading "the parts we recognise" would produce confident nonsense.

    ``details`` always carries three keys, because a user who sees this error needs to know what
    they have and what would read it:

    * ``schema`` — the payload type, e.g. ``"benchmark.result"``.
    * ``received`` — the version string found in the document.
    * ``supported`` — every version this build accepts, formatted, in ascending order. An empty
      list means this build knows the schema name but publishes no version of it yet.

    Attributes:
        code: ``"SCHEMA_VERSION_UNSUPPORTED"``, stable and part of the public contract.
    """

    code: ClassVar[str] = "SCHEMA_VERSION_UNSUPPORTED"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        """Build the error.

        Args:
            message: What was received, what is supported, and what the caller can do — upgrade
                the reader, or re-export from the producer at an older version.
            details: Structured context; see the class docstring for the keys callers rely on.
        """
        super().__init__(message, details=details)
