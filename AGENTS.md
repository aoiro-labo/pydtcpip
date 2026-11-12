# AGENTS.md

## Purpose and scope

pydtcpip is an unofficial asyncio-based Python library and CLI for receiving recordings from home DLNA / DTCP-IP devices in their original quality. It supports streaming, GET Move, and receiving a POST Move as a generic NAS. Leave the handling of received content to the user.

The project does not implement recorder scheduling, proprietary preparation for mobile downloads, remote access, Enhanced Full Authentication, PCP2, or a DTCP Source for playback distribution. Prefer original-format resources (`DLNA.ORG_CI=0`); select converted resources only when explicitly requested.

## Transfer safety

- GET Move and incoming transfers consume a source copy. If only the final Move remains or copying is prohibited, the source recording is deleted. The displayed remaining copy count excludes the final Move.
- Before an interactive CLI Move, show the recording, copy count and acquisition status, and warn when the source recording will be deleted. Skip confirmation with `--yes` or non-terminal stdin. Document the same risk for incoming transfers.
- For Move, persist the entire recording before sending FINALIZE. After a verified finalize response, commit the sink before sending COMPLETE. If the response is lost, retain the full data and resume state; the source may already have consumed a copy. Distinguish a cancellation request from its acknowledgment.
- Keep metadata copy counts, `protocolInfo` protection attributes and PCP E-EMI distinct. Preserve their source, observation time and acquisition status (`known`, `not_observed`, `omitted`, `unsupported`); never convert an omitted value or an error to zero or unsupported. Retain raw XML, `protocolInfo` and HTTP headers for later interpretation.
- Track received HTTP bytes, decrypted bytes and written bytes separately, including when the total is unknown. Report receipt, persistence, finalization, completion and cancellation as distinct events; keep copy-count requery separate from completion.

## Credentials and API

- Users provide the 88-byte device certificate and 20-byte private key. `DeviceCredentials` accepts bytes, independently of storage; `DeviceStore` is an explicit opt-in for file management. Never include private keys, exchange keys or resume-state secrets in logs, events or exception messages.
- An SRM is optional: authenticate as version 0 when absent and deliver newer verified SRMs through `on_srm_update`. The CLI persists SRMs with `DeviceStore`; do not bundle an SRM in the package.
- Public APIs are asynchronous. Keep connections and credentials in stateful clients, and represent recordings, resources, protection information, events and resume state as independent values. DTCP operations accept both `Resource` and URL strings.
- Deliver progress through `on_event`; await the streaming `on_data` callback to apply backpressure. Move sinks provide `write`, `persist`, `commit` and `discard`; preserve the ordering and recovery guarantees above.
- Use standard `logging` for library logs. CLI commands that write media to standard output must send logs and progress to standard error.

## Device compatibility

Keep vendor-specific behavior in family profiles and communication-dependent extensions, isolated from the core and other families. Profiles form a tree rooted in generic DLNA, inherit unspecified behavior, and select the deepest match. Use device descriptions, namespaces, services or actions to distinguish families where possible. Treat ties at the same depth as test failures. Extensions use `MediaServer` and shared DTCP operations.

When adding a family, preserve other fixtures and behavior. Test all existing profiles, unique matching, import boundaries and generic DLNA behavior. Core changes needed for an extension should provide a generic hook with an unchanged default; do not weaken tests to accommodate a device.

The receiver advertises itself as pydtcpip, not as another manufacturer's device. It uses standard DLNA upload and `X_GetDLNAUploadProfiles`; add proprietary actions only after observing a device that requires them. REGZA 43Z570L requires `X_move_support` and extension namespaces declared on the elements themselves. For POST Move, authenticate before receiving the body, return `100 Continue` with `BLKMove.dtcp.com`, and send the final HTTP response before FINALIZE; that HTTP response does not indicate Move completion.

DBR-Z620 discards its resume state immediately if the control connection drops after it accepts FINALIZE. It also closes unauthenticated connections that send FINALIZE; authenticate normally before retrying finalization or completion. Its copy count can take around 80 seconds to update. REGZA 43Z570L includes broadcast network and service IDs only in BrowseDirectChildren, not BrowseMetadata. Preserve these device-specific behaviors when changing the affected paths.

`dump` saves device responses unchanged by default and requires no credentials. With `--mask-private`, retain only known non-sensitive values, replace embedded identifiers with documentation values, and redact all other values, including unknown elements, attributes, CDATA, comments, URL paths and headers. Keep redacted output usable as test fixtures.

## Implementation and testing

Use Python 3.13+ and uv. Use aiohttp for HTTP, ElementTree for UPnP XML, Pydantic for models, pydantic-settings for CLI credentials, cryptography and ecdsa for cryptography, and Typer and Rich for the CLI. Use Ruff with single quotes and a 120-character line length, Pyright strict, and pytest with AnyIO's asyncio backend.

Write CLI text, exceptions, logs, docstrings and comments in natural English. Omit final periods in code comments by default. Document arguments and non-None return values in Google-style docstrings, including private functions; omit sections that do not apply. Preserve uppercase abbreviations in names such as `DTCPClient`.

Normal tests must not depend on a user's devices or network. Connect a test-only fake source and sink in one process, with a test authority replacing DTLA public keys. Implement the source protocol independently of the sink; verify shared content-key derivation and Move MAC calculations against known values validated with a real device. Cover fixed-length and chunked transfers, interruption, authentication and finalization failures, resumption and cancellation. Do not include copy-consuming operations in automated tests.

The repository is public. Never include actual credentials, personal identifiers, recording content, raw device responses or private environment details in published code and fixtures. Use sanitized synthetic fixtures.

Describe real-device test results, model names, observed behavior and profiles when they explain compatibility. Present the code consistently as an implementation of the DTCP-IP and DLNA specifications. Do not identify which firmware, devices or applications were analyzed, or describe the analysis methods, in code, comments or documentation outside the README.

The README may include general research context and indirect hints that help users ask an LLM about obtaining their own credentials. Keep those hints general enough that they do not identify the specific products analyzed or disclose the methods used.

Commit message prefixes are `Add:`, `Fix:`, `Update:`, `Refactor:`, `Build(deps):`, and `Release:`.
