# Contributing

This project is intentionally small. Contributions should keep the public edition synthetic, deterministic, and easy to inspect.

## Development

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/quantengine-public demo
```

## Rules

- Use synthetic examples only.
- Do not add exchange adapters, account data, private paths, or production configuration.
- Keep CLI outputs deterministic where practical.
- Add or update tests for behavior changes.

## Public Data Policy

Examples should use generic order/payment identifiers such as `order-001` and `payment-001`.
