# 0014. The eval judge model: GPT-6 Luna

- **Status:** Accepted
- **Date:** 2026-11-09

## Context
0011 calls for an LLM judge that grades correctness, faithfulness and injection resistance, is calibrated against about 30 of the owner's hand grades, and comes **from a different model family than the generators it grades**. 0009 compares three generators (Claude Haiku 5.5, Gemma 4 and Qwen 3.6), so Anthropic, Google and Qwen models are all excluded. 0009 also requires a strict zero-data-retention (ZDR) endpoint.

Cost basis: each judged answer is about 3,500 input tokens (the rubric, the question, the reference answer, five passages and the answer) and about 200 output tokens. One dev run is about 135 judged items (120 gold questions plus the injection set). ADR 0011 plans roughly 8 comparison runs.

Facts come from OpenRouter's public `/api/v1/models` and `/api/v1/endpoints/zdr`, **checked 2026-11-09**. Prices change, so re-check them before relying on these numbers.

## Options considered
| Model | Family | $/M in / out | Per dev run | ~8 runs | ZDR providers |
|---|---|---|---|---|---|
| `openai/gpt-6-luna` | OpenAI (Sep 2026) | 0.10 / 0.50 | ~$0.06 | ~$0.50 | Azure |
| `openai/gpt-5.6-luna` | OpenAI (Jul 2026) | 0.20 / 1.20 | ~$0.13 | ~$1.00 | Azure |
| `openai/gpt-5-mini` | OpenAI (2025) | 0.25 / 2.00 | ~$0.17 | ~$1.40 | Azure |
| `openai/gpt-5.4-mini` | OpenAI | 0.75 / 4.50 | ~$0.48 | ~$3.80 | Azure |
| `mistralai/mistral-large-4-0` | Mistral | 0.70 / 2.10 | ~$0.39 | ~$3.10 | Mistral |
| `deepseek/deepseek-v4.1-flash` | DeepSeek | 0.05 / 0.57 | ~$0.04 | ~$0.30 | 25 providers |
| `anthropic/claude-haiku-5.5` | Anthropic | 0.10 / 0.50 | n/a | n/a | **Rejected:** same family as the default generator |

- **Claude Haiku 5.5** is cheap and capable, but it would grade its own family's answers. Using it would mean dropping Claude from the generator comparison, which defeats the purpose of that comparison.
- **The "-pro" Luna variants** are the same model run with heavier reasoning. They cost more per call for a task (scoring against a rubric) that light reasoning should handle. They remain the next step up if calibration disappoints.
- **GPT-5.4 mini and Mistral Large 4** cost 6–8× more without any measured evidence that they grade better here.
- **DeepSeek V4.1 Flash** is the cheapest option and the most resilient (25 ZDR providers), and a reasonable alternative. The owner preferred the newer OpenAI tier.

## Decision
`JUDGE_MODEL` defaults to **`openai/gpt-6-luna`**. It is still overridable through the environment, and the runner still refuses a judge from the same family as the generator it grades.

Supporting changes:
- **The judge's output cap goes from 500 to 2,000 tokens.** Luna is a reasoning model, and its hidden reasoning tokens count against `max_tokens`. A 500-token cap could leave nothing for the verdict. The higher cap adds at most about $0.001 per call.
- **Luna's price goes into the cost meter's fallback table,** so a response without `usage.cost` is still priced accurately.

## Why
- **It is the cheapest model from a family distinct from all three generators.** A full comparison series costs about $0.50 in judging, well inside the $5 key limit, so cost won't discourage re-running evals.
- **A wrong choice gets caught.** Calibration (Cohen's kappa against the owner's hand grades) measures how well the judge actually grades. If agreement is poor, the next step is `gpt-5.6-luna` or the `-pro` variant, recorded in a new ADR together with the kappa that motivated the switch.

## Consequences
- **One ZDR provider (Azure).** If Azure is down, judging pauses. The eval runs offline, so waiting is acceptable. The runner records judge failures per item rather than losing the answers.
- **Probably no temperature control.** OpenRouter's catalogue doesn't list `temperature` among Luna's supported parameters. We expect OpenRouter to drop the `temperature: 0` our client sends, rather than the endpoint rejecting the request. If so, grades may vary slightly between runs, which makes the calibration figure (and any comparison between runs) slightly noisier. Reports state the judge model, so readers can take that into account.
- **The cost and token assumptions are estimates.** The figure of about 200 output tokens per verdict is a guess, and hidden reasoning may raise it. Reports record the actual judge cost separately from the answering cost.
- **To be confirmed on the first judged run.** Before any full run, the eval workflow (`evals/README.md`) includes a 5-item judged smoke run. It checks that requests are accepted, that 2,000 tokens leave room for the verdict, and what a judged item really costs.
- **Revisit** if calibration kappa is poor, if Luna loses its ZDR endpoint, or if a generator from the OpenAI family joins the comparison.
