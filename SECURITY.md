# Security Policy

This repository is a public, synthetic backend verification project.

Do not submit:

- API keys, tokens, passwords, or SSH details.
- Private hostnames or local absolute paths.
- Real account, order, position, or balance data.
- Exchange adapters or production deployment scripts.
- Private strategy logic or proprietary configuration.

Before release, run:

```bash
python scripts/public_safety_scan.py
python scripts/public_safety_scan.py --history
```

The scan reports only file or commit location plus rule id. It does not reprint matched sensitive text into logs.

If you find sensitive content in the repository, open a private security report or contact the maintainer directly.
