"""Secure, local-only RQData initialization helper.

The credential is entered interactively with echo disabled, is passed directly
to rqdatac.init(), and is never written to disk or printed. This script does
not call any RQData data-query API.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import importlib.metadata
import io


EXPECTED_VERSION = "3.5.2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize rqdatac 3.5.2 using a hidden, non-persistent URI prompt."
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Verify the installed SDK version without initializing or prompting.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    installed_version = importlib.metadata.version("rqdatac")
    if installed_version != EXPECTED_VERSION:
        print("status: BLOCKED_BY_RQDATAC_VERSION_MISMATCH")
        print(f'expected_version: "{EXPECTED_VERSION}"')
        print(f'installed_version: "{installed_version}"')
        return 2

    import rqdatac

    if args.self_check:
        print("status: RQDATAC_IMPORT_READY")
        print(f'rqdatac_version: "{installed_version}"')
        print("rqdata_initialized: false")
        return 0

    credential = getpass.getpass("RQData URI (hidden; not stored): ").strip()
    if not credential:
        print("status: OPERATOR_RQDATA_CONFIGURATION_REQUIRED")
        print("credential_values_exposed: false")
        return 3

    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            rqdatac.init(uri=credential)
    except Exception as exc:
        kind = type(exc).__name__
        message = str(exc).lower()
        if "license" in message or "expired" in message:
            category = "LICENSE_INVALID_OR_EXPIRED"
        elif "auth" in message or "password" in message:
            category = "CREDENTIAL_REJECTED"
        elif "connect" in message or "network" in message or "timeout" in message:
            category = "NETWORK_UNAVAILABLE"
        elif isinstance(exc, ValueError):
            category = "CONNECTION_CONFIGURATION_INVALID"
        else:
            category = "UNKNOWN_INITIALIZATION_ERROR"
        print("status: BLOCKED_BY_RQDATA_INITIALIZATION")
        print(f"error_type: {kind}")
        print(f"error_category: {category}")
        print("credential_values_exposed: false")
        return 4
    finally:
        credential = ""
        captured.close()

    print("status: RQDATA_INITIALIZATION_READY")
    print(f'rqdatac_version: "{installed_version}"')
    print("credential_values_exposed: false")
    print("real_data_query_performed: false")
    print("data_files_generated: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
