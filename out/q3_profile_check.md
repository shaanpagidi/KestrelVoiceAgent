# Q3 localization profile checks

Static checks only; they verify configuration and scenario coverage, not ASR accuracy, native fluency, or recorded calls.

| Market | Sector | ASR config | TTS config | Localization examples | Scenario prompts | Static result |
|---|---|---|---|---:|---:|---|
| philippines | life insurance / bancassurance | Deepgram nova-3 / tl | Azure Speech fil-PH-BlessicaNeural | 3 | 5 | PASS |
| indonesia | multifinance / consumer finance | Deepgram nova-3 / id | Azure Speech id-ID-GadisNeural | 3 | 6 | PASS |

## Not measured yet

No provider credentials or native-speaker WAV samples are configured in this workspace. ASR quality, Taglish/Indonesian code-switching, TTS naturalness, and regional-accent performance remain unmeasured. Record and review at least two calls per market before claiming those requirements complete.
