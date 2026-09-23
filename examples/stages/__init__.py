"""Example custom stages (ADR 0020). Each is a complete plugin: register
one with

    "stages": [{"path": "examples.stages.target_attainment.TargetAttainment",
                "options": {"target": 3000000}}]

in config.json, or AGENTIC_OS_STAGES=examples.stages.target_attainment.TargetAttainment
for one that needs no options."""
