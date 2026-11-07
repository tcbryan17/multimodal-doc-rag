"""The evaluation harness (ADR 0011). Runs outside pytest, makes real model calls, costs money.

Layout: `gold` (question schema + JSONL), `metrics` (pure scoring), `judge` (LLM grader),
`runner` + `report` (run questions, write reports), `draft` (model-drafted gold items),
`calibration` (judge vs human agreement), `index` (eval-only database for injection tests).
"""
