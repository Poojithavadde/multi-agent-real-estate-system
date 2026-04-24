# Shared Utilities

This folder contains shared A2A conventions used across all agent repositories:

- Agent Card format (`id`, `name`, `protocol`, `capabilities`, `endpoints`)
- REST-based A2A endpoint naming (`/a2a/...`)
- Structured JSON responses with `status`
- Logging standard using timestamped Python logger output

Each agent is independently deployable and can run as its own service.
