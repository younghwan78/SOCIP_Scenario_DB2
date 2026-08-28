"""Cross-project projection — calibrate a project's simulation against its own
measurements, then project a target project's simulation into a measurement-like
estimate.

Flow (see ``docs/guides/measurement/projection-guide-ko.md`` and
``docs/contracts/data/measurement-evidence-contract.md`` §3):

    U sim (calculation) + U measurement  ->  Calibration (correction factors)
    Calibration + V sim (calculation)    ->  V projected evidence
                                              (method=projection, derived_from)
    V projected + V measurement (later)  ->  projection error report
"""
