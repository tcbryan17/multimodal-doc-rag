# 11. Answer metrics and the LLM judge

## What it does
Answers are scored two ways. Rules first. `is_abstention` is true if the answer equals the fixed "I don't know" sentence after normalising case and whitespace, or starts with it. `numeric_match` extracts every number in the reference (it understands $, commas, %, thousand/million/billion, minus signs and bracketed negatives) and requires every one to appear in the answer, ignoring `[n]` markers. It returns `None` when the reference has no number. Then an LLM judge, `openai/gpt-6-luna`, grades correctness (0, 0.5 or 1), faithfulness (0 or 1) and, for injection items, whether the attack was followed. The judge gets the question, the reference answer, the numbered passages with the figure images the generator saw, and the answer, all fenced as data. `parse_verdict` takes the first valid JSON object and rejects anything out of range. `check_judge_config` refuses a judge from the same model family as the generator. The output cap is 2,000 tokens because the judge is a reasoning model.

## Where it lives
- `src/multimodal_doc_rag/evals/metrics.py::is_abstention`
- `src/multimodal_doc_rag/evals/metrics.py::numeric_match`
- `src/multimodal_doc_rag/evals/metrics.py::extract_numbers`
- `src/multimodal_doc_rag/evals/judge.py::JUDGE_SYSTEM`
- `src/multimodal_doc_rag/evals/judge.py::build_judge_messages`
- `src/multimodal_doc_rag/evals/judge.py::parse_verdict`
- `src/multimodal_doc_rag/evals/judge.py::check_judge_config`
- `src/multimodal_doc_rag/evals/judge.py::judge_fingerprint`
- `src/multimodal_doc_rag/evals/judge.py::OpenRouterJudge`
- `src/multimodal_doc_rag/evals/judge.py::JUDGE_MAX_TOKENS`

## What was chosen and why
ADR 0011: an LLM judge calibrated against the owner's hand grades, from a different model family than the generators, with numeric facts also checked by exact match. ADR 0014 picked `openai/gpt-6-luna`: the cheapest model from a family outside Claude, Gemma and Qwen with a zero-retention endpoint (Azure), at $0.10 in and $0.50 out per million tokens, about $0.06 per dev run. ADR 0017 added the figure images, because a judge shown only the description would mark a value read correctly off a chart as unsupported. The judge is itself injectable, so passages and answers are fenced and the prompt says that an attempt to instruct the judge is evidence about the answer.

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| Rules only | Cannot judge explanations | Short factual answers only |
| The owner grades everything | Most trustworthy but blocks frequent runs | A one-off final audit |
| Claude Haiku 5.5 as judge | Same family as the default generator, so it would flatter its own answers | If the generator were not Claude |
| `gpt-5.6-luna`, `gpt-5-mini`, `gpt-5.4-mini`, Mistral Large 4 | Dearer, with no measured gain (6 to 8 times for the last two) | If calibration kappa came out poor |
| `deepseek/deepseek-v4.1-flash` | Cheapest and the most resilient (25 ZDR providers), and a reasonable alternative. The owner preferred the newer OpenAI tier. | If Azure were down for long or cost mattered more |
| Judge sees text only | FAA faithfulness would read low for a reason unrelated to the system | If images were removed from the product |

## Evidence
- Text smoke run `evals/reports/20261114T161029Z-judge-smoke.md`, and figure smoke run `evals/reports/20261115T141659Z-judge-smoke-figures.md`: 3 questions, every judge call carried 3 or 4 images and none failed, so the ZDR endpoint accepts images. Whole run cost $0.0112.
- ADR 0014 estimate: about 3,500 input and 200 output tokens per judged answer. The real output cost is still unconfirmed on a full run.
- Not measured yet: how well the judge agrees with the owner (guide 12), and run-to-run variance. ADR 0014 expects `temperature: 0` to be dropped for Luna, so repeated grades may vary. To measure it, grade the same 20 answers three times and compare.

## Interview questions
1. Why must the judge come from a different model family than the generator? How does the code enforce it?

**Your answer:**

2. The judge is a language model reading text written by another language model. Name two ways it can be attacked and what the code does about each.

**Your answer:**

3. Why does the judge need the figure images? What would happen to faithfulness on figure questions without them?

**Your answer:**

4. `numeric_match` requires every number in the reference to appear in the answer. Give a case where it wrongly fails and a case where it wrongly passes.

**Your answer:**

5. Luna is a reasoning model. Why is the output cap 2,000 and not 500, and what failure did that prevent?

**Your answer:**
