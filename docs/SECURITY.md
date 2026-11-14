# Security baseline

- Keep API keys and provider credentials server-side in environment variables; never commit `.env`.
- Validate request parameters with Pydantic and constrain ranges / input lengths.
- Use provider timeouts, bounded retries, response-size limits and request rate limits.
- Configure CORS for exact frontend origins in deployment; do not use wildcard origins with credentials.
- Return generic client errors; keep stack traces and secrets out of responses.
- Avoid unsafe HTML rendering and validate any external links/content.
- Set security headers and a suitable Content Security Policy at deployment.
- Pin dependencies and run dependency vulnerability scans.
- Do not add authentication until accounts or private resources require it; if added, enforce authorization server-side.
- Do not expose filesystem paths, model internals, credentials, or raw provider error details.
- Add tests for invalid input, rate limits, provider failures, and malformed datasets.
- Treat model outputs as estimates, not certainty or betting guarantees.
