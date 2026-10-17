# Data, rules and provenance

[中文说明](data-and-rules.zh-CN.md)

## Sources

- [FastF1 project and documentation](https://github.com/theOehrly/Fast-F1): optional historical
  session adapter. See the upstream project for access, cache and data-use documentation.
- [FIA regulations portal](https://www.fia.com/regulation/category/110): find the applicable
  sporting regulation version and event documents before constructing a rules configuration.

The adapter expects FastF1 3.8.x-compatible metadata. Retain only non-pit, accurate, green
track laps with explicit dry compound labels and positive finite observations. Both FastF1
entry points load race control messages so that deleted-lap flags can be populated. Missing
or unknown `Deleted` flags fail the session instead of treating unknown laps as valid;
`--allow-partial` can explicitly skip a failed year in the cycle adapter. Old offline caches
without race control messages need an explicit online refill before they can pass this check.
Deleted laps are excluded. Missing temperature is retained as missing; the current
fit and held-out evaluation use reference temperature rather than pretending to estimate
temperature response from those observations. Cleaned-out counts and requested/loaded years
are recorded. Metadata exclusion counts overlap (one lap can have several reasons); numeric
exclusions are counted after metadata filtering. Duplicates fail validation.

See the [bounded real-validation attempt](real-validation-2026-10-17.md) for the actual
network blockers and the reproducible train/holdout protocol; no real accuracy was measured.

## Scope of rules

The example configuration is a user-defined research scenario motivated by historical dry
tyre constraints. It is not a transcription of complete FIA rules and does not certify
compliance. It records season, event, version, source description, minimum compounds and
minimum stints. Users must specify appropriate constraints for each study. Track-specific
exceptions, mandated nominations, wet-tyre use, tyre inventory and event-specific directives
are not automatically enforced. The software never grants a rule exemption just because
rain is reported. Per-compound age limits are scenario inputs, not manufacturer safety advice.

## Redistribution

Only original code, documentation and synthetic examples are intended for this repository's
MIT distribution. FIA PDFs, FastF1 caches, fetched race data, generated local reports and
presentation materials remain outside the default tracked source set. The MIT license does
not grant rights to third-party material. Consult source terms before redistributing datasets.
The project does not bundle logos or claim affiliation.

Run manifests include SHA-256 of normalized input data, environment versions, explicit
modelling priors, coverage and rule scope. Data downloaded today may differ from a previous
snapshot. Preserve your local exported laps plus manifest when reproducing experiments.
