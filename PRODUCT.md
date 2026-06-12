# Product

## Register

product

## Users

The bot is operated through Telegram by its owner or permitted chat members.
Users expect the existing commands, signal messages, and scanning behavior to
remain unchanged.

## Product Purpose

The application scans configured Bybit futures pairs with the existing Smart
Money Concepts logic, sends Telegram signals, and monitors the existing A/B
prediction scenarios. Success means the current bot runs continuously on a
Beget Linux VPS through Docker Compose without changing its trading or
messaging behavior.

## Brand Personality

Technical, direct, and signal-focused. Existing Russian copy, Markdown, and
emoji usage are part of the current product contract and must be preserved.

## Anti-references

Do not redesign the Telegram output, simplify the analysis, copy trading logic
from the architectural reference bot, add a web interface, or introduce new
commands and access-control behavior.

## Design Principles

1. Preserve observable bot behavior exactly.
2. Separate responsibilities without rewriting the underlying logic.
3. Keep deployment simple for a single Linux VPS.
4. Keep secrets outside the image and repository.
5. Persist the editable coin list across container rebuilds.

## Accessibility & Inclusion

No visual interface is being introduced. Existing Telegram message formatting
must remain unchanged.
