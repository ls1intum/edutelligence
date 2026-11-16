# Athena: A system to support (semi-)automated assessment of exercises

---
> **Note**
> **Looking for Athena, the reference implementation of CoFee by Jan-Philip Bernius?**
> → https://github.com/ls1intum/Athena-CoFee
---


![Athena Logo](./playground/public/logo.png)

## What is Athena?
Athena is an advanced system designed to assist educators by providing (semi-)automated assessments for various types of academic exercises. Through its integration with learning management systems (LMS), Athena offers an efficient and innovative way to evaluate students' work in large courses. The system has been expanded from its original focus on textual exercises to now include support for programming exercises and has plans for future support of additional exercise types such as UML modeling and mathematics.

**Documentation:** [https://ls1intum.github.io/edutelligence/athena/](https://ls1intum.github.io/edutelligence/athena/)

## LLM cost reporting

LLM modules forward a provider's `usage.cost` as `totalCostUsd` with
`costSource: PROVIDER` when the response explicitly states `cost_currency: USD`.
The amount must be finite and non-negative; a reported zero is kept. The
LangChain ChatOpenAI nonstreaming response retains this information in its raw
token usage. If the model or streaming adapter drops those extra usage fields,
Athena uses an explicitly configured USD estimate instead.

The optional environment variables
`LLM_DEFAULT_MODEL_COST_PER_MILLION_INPUT_TOKEN_USD`,
`LLM_DEFAULT_MODEL_COST_PER_MILLION_OUTPUT_TOKEN_USD`,
`LLM_DEFAULT_MODEL_COST_PER_MILLION_CACHED_INPUT_TOKEN_USD` and
`LLM_DEFAULT_MODEL_COST_PER_MILLION_CACHE_WRITE_INPUT_TOKEN_USD` set the fallback
USD rates. Each token class used by the call needs its own rate. Estimates are
sent with `costSource: CONFIGURATION`; missing prices stay unpriced. The older
variables without `_USD` retain their existing meaning and never establish a
USD amount.
