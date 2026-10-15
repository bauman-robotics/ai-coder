# Pricing — модели DeepSeek (2026-10-16)

Источник: https://api-docs.deepseek.com/quick_start/pricing

## Модели

| | deepseek-flash | deepseek-v4-pro |
|---|---|---|
| Version | DeepSeek-V4.1-Flash | DeepSeek-V4-Pro-0813 |
| Context | 1M | 1M |
| Max output | 384K | 384K |
| Thinking mode | ✓ (default) | ✓ (default) |
| Vision | ✓ | ✗ |
| Concurrency | 2500 | 500 |

## Цены (per 1M tokens, USD)

### Input (cache hit)

| | Off-peak | Peak |
|---|---|---|
| Flash | $0.003 | $0.006 |
| V4-Pro | $0.022 | $0.044 |

### Input (cache miss)

| | Off-peak | Peak |
|---|---|---|
| Flash | $0.15 | $0.30 |
| V4-Pro | $0.66 | $1.32 |

### Output

| | Off-peak | Peak |
|---|---|---|
| Flash | $0.60 | $1.20 |
| V4-Pro | $1.98 | $3.96 |

## Ключевое

- **Off-peak = ×2 дешевле peak.** Peak: 01:00-04:00, 06:00-10:00 UTC, Пн-Пт.
- **Flash ×5 дешевле V4-Pro** (input miss), **×3.3** (output).
- **Cache hit ×50 дешевле miss** (Flash: $0.003 vs $0.15).
- **Reasoning** — оплачивается как **output**.
- **Оплата** — с баланса (granted first, потом topped-up).

## Ссылки

- https://api-docs.deepseek.com/quick_start/pricing
- https://api-docs.deepseek.com/guides/thinking_mode
