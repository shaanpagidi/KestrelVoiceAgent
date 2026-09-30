# Q4 deterministic signal checks

Synthetic transcript fixtures only; no audio, ASR, LLM, or network delivery was used.

| Scenario | Result | Detail |
|---|---|---|
| Skipped required disclosure | PASS | A compliance nudge is emitted after the configured disclosure deadline. |
| Disclosure recognition | PASS | recorded/recording variants count as the disclosure. |
| Missed cross-sell opportunity | PASS | A second-vehicle mention produces a short agent suggestion. |
| Risky promise | PASS | A guarantee statement produces a high-priority compliance alert. |
| Rising frustration | PASS | Frustration language prompts acknowledgement and human-help guidance. |
| Payment difficulty | PASS | Hardship language suggests the approved support or callback path. |
| Topic shift | PASS | A payment-to-coverage shift suggests acknowledging and confirming the new intent. |
| Noisy / ambiguous input | PASS | Low-confidence transcript does not create a nudge. |
| Duplicate suppression / cooldown | PASS | Repeated same-group frustration nudge is suppressed during cooldown. |
| Nudge expiry | PASS | Expired nudges are removed from the active feed. |

Result: 10/10 passed.

Signal detection latency: P50 0.072 ms; P95 0.256 ms (in-process synthetic transcript path).
ASR and end-to-end audio/display latency are not measured in this report.

Zero nudges from one low-confidence noisy fixture (n=1). This is a control check, not a statistically meaningful false-positive rate.
