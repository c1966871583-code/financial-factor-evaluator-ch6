"""FIN-R1A: conservative A-share financial announcement timing governance.

The module derives the first trading date on which a financial observation may
enter an evaluation cross-section.  The approved policy is deliberately
conservative: every announcement becomes effective on the first trading day
strictly after its local publication date.  Same-day pre-market effectiveness
is not enabled by this implementation.

This module is pure and deterministic.  It performs no network, database,
calendar-service, or production-data access.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo


TIMING_POLICY_VERSION = "FIN-R1A-CONSERVATIVE-v1.0"
MARKET_TIMEZONE = "Asia/Shanghai"

PIT_EFFECTIVE_DATE_UNVERIFIED = "PIT_EFFECTIVE_DATE_UNVERIFIED"
TRADING_CALENDAR_UNAVAILABLE = "TRADING_CALENDAR_UNAVAILABLE"
ANNOUNCEMENT_TIMESTAMP_INVALID = "ANNOUNCEMENT_TIMESTAMP_INVALID"
ANNOUNCEMENT_TIMEZONE_UNVERIFIED = "ANNOUNCEMENT_TIMEZONE_UNVERIFIED"
EFFECTIVE_DATE_BEFORE_PUBLICATION = "EFFECTIVE_DATE_BEFORE_PUBLICATION"
EFFECTIVE_DATE_POLICY_MISMATCH = "EFFECTIVE_DATE_POLICY_MISMATCH"
RETURN_START_BEFORE_EFFECTIVE_DATE = "RETURN_START_BEFORE_EFFECTIVE_DATE"
REVISION_EFFECTIVE_DATE_INVALID = "REVISION_EFFECTIVE_DATE_INVALID"


class TimingStatus(str, Enum):
    PASSED = "passed"
    BLOCKED = "blocked"


class TimestampQuality(str, Enum):
    DATE_ONLY = "date_only"
    TRUSTED = "trusted_timestamp"
    INVALID = "invalid"
    UNVERIFIED_TIMEZONE = "unverified_timezone"


class MarketSessionClassification(str, Enum):
    DATE_ONLY = "date_only"
    PRE_MARKET = "pre_market"
    IN_SESSION = "in_session"
    POST_MARKET = "post_market"
    NON_TRADING_DAY = "non_trading_day"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class TimingIssue:
    code: str
    message: str
    field_name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", copy.deepcopy(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_name": self.field_name,
            "details": copy.deepcopy(self.details),
        }


@dataclass(frozen=True)
class FinancialTimingPolicy:
    """Frozen timing policy and an explicit, versioned trading calendar."""

    trading_days: tuple[str, ...]
    trading_calendar_version: str
    timing_policy_version: str = TIMING_POLICY_VERSION
    timezone: str = MARKET_TIMEZONE
    pre_market_same_day_allowed: bool = False
    market_open: time = time(9, 30)
    market_close: time = time(15, 0)

    def __post_init__(self) -> None:
        if not isinstance(self.trading_calendar_version, str) or not self.trading_calendar_version.strip():
            raise ValueError("trading_calendar_version must be non-empty")
        if not isinstance(self.timing_policy_version, str) or not self.timing_policy_version.strip():
            raise ValueError("timing_policy_version must be non-empty")
        if self.timezone != MARKET_TIMEZONE:
            raise ValueError(f"timezone must be {MARKET_TIMEZONE}")
        if self.pre_market_same_day_allowed:
            raise ValueError(
                "same-day pre-market effectiveness is not authorized by CH6-G0"
            )
        if self.market_open >= self.market_close:
            raise ValueError("market_open must be earlier than market_close")

        normalized: list[str] = []
        for raw_day in tuple(self.trading_days):
            try:
                normalized.append(_parse_date(raw_day).isoformat())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid trading day {raw_day!r}") from exc
        if len(normalized) != len(set(normalized)):
            raise ValueError("trading_days must not contain duplicates")
        object.__setattr__(self, "trading_days", tuple(sorted(normalized)))

    def first_trading_day_after(self, publication_date: date) -> date | None:
        for raw_day in self.trading_days:
            trading_day = date.fromisoformat(raw_day)
            if trading_day > publication_date:
                return trading_day
        return None

    def is_trading_day(self, candidate: date) -> bool:
        return candidate.isoformat() in self.trading_days


@dataclass(frozen=True)
class FinancialTimingObservation:
    code: Any
    publish_date: Any
    announcement_timestamp: Any = None
    announcement_timezone: Any = None
    statement_version: Any = None
    source_record_id: Any = None
    provided_effective_date: Any = None
    return_start_date: Any = None


@dataclass(frozen=True)
class TimingAudit:
    code: str | None
    statement_version: str | None
    source_record_id: str | None
    timing_policy_version: str
    trading_calendar_version: str
    timezone: str
    publish_date: str | None
    announcement_timestamp: str | None
    timestamp_quality: str
    market_session_classification: str
    derived_effective_date: str | None
    provided_effective_date: str | None
    effective_date_validation_status: str
    decision_reason_code: str
    return_start_validation_status: str
    overall_status: str
    errors: tuple[TimingIssue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "statement_version": self.statement_version,
            "source_record_id": self.source_record_id,
            "timing_policy_version": self.timing_policy_version,
            "trading_calendar_version": self.trading_calendar_version,
            "timezone": self.timezone,
            "publish_date": self.publish_date,
            "announcement_timestamp": self.announcement_timestamp,
            "timestamp_quality": self.timestamp_quality,
            "market_session_classification": self.market_session_classification,
            "derived_effective_date": self.derived_effective_date,
            "provided_effective_date": self.provided_effective_date,
            "effective_date_validation_status": self.effective_date_validation_status,
            "decision_reason_code": self.decision_reason_code,
            "return_start_validation_status": self.return_start_validation_status,
            "overall_status": self.overall_status,
            "errors": [issue.to_dict() for issue in self.errors],
        }


class _TimingValidationError(ValueError):
    def __init__(self, code: str, message: str, field_name: str) -> None:
        super().__init__(message)
        self.code = code
        self.field_name = field_name


def evaluate_financial_timing(
    observation: FinancialTimingObservation,
    policy: FinancialTimingPolicy,
) -> TimingAudit:
    """Return a complete timing audit; invalid observations fail closed."""

    code = _optional_text(observation.code)
    statement_version = _optional_text(observation.statement_version)
    source_record_id = _optional_text(observation.source_record_id)
    publish_iso = _display_date(observation.publish_date)
    timestamp_display = _display_value(observation.announcement_timestamp)
    provided_iso = _display_date(observation.provided_effective_date)

    timestamp_quality = TimestampQuality.DATE_ONLY.value
    session = MarketSessionClassification.UNCLASSIFIED.value
    effective_status = "not_checked"
    return_status = "not_provided"

    try:
        publication_date = _parse_date(observation.publish_date)
    except (TypeError, ValueError):
        return _blocked_audit(
            policy=policy,
            observation=observation,
            code=PIT_EFFECTIVE_DATE_UNVERIFIED,
            message="publish_date must be a valid calendar date",
            field_name="publish_date",
            publish_date=publish_iso,
            announcement_timestamp=timestamp_display,
            provided_effective_date=provided_iso,
            timestamp_quality=TimestampQuality.INVALID.value,
            session=session,
            effective_status=effective_status,
            return_status=return_status,
        )
    publish_iso = publication_date.isoformat()

    if _is_missing(observation.announcement_timestamp):
        timestamp_display = None
        session = MarketSessionClassification.DATE_ONLY.value
    else:
        try:
            local_timestamp = _parse_announcement_timestamp(
                observation.announcement_timestamp,
                observation.announcement_timezone,
                policy,
            )
        except _TimingValidationError as exc:
            quality = (
                TimestampQuality.UNVERIFIED_TIMEZONE.value
                if exc.code == ANNOUNCEMENT_TIMEZONE_UNVERIFIED
                else TimestampQuality.INVALID.value
            )
            return _blocked_audit(
                policy=policy,
                observation=observation,
                code=exc.code,
                message=str(exc),
                field_name=exc.field_name,
                publish_date=publish_iso,
                announcement_timestamp=timestamp_display,
                provided_effective_date=provided_iso,
                timestamp_quality=quality,
                session=session,
                effective_status=effective_status,
                return_status=return_status,
            )
        if local_timestamp.date() != publication_date:
            return _blocked_audit(
                policy=policy,
                observation=observation,
                code=ANNOUNCEMENT_TIMESTAMP_INVALID,
                message="announcement_timestamp local date must equal publish_date",
                field_name="announcement_timestamp",
                publish_date=publish_iso,
                announcement_timestamp=local_timestamp.isoformat(),
                provided_effective_date=provided_iso,
                timestamp_quality=TimestampQuality.INVALID.value,
                session=session,
                effective_status=effective_status,
                return_status=return_status,
            )
        timestamp_display = local_timestamp.isoformat()
        timestamp_quality = TimestampQuality.TRUSTED.value
        session = _classify_market_session(local_timestamp, publication_date, policy)

    effective_date = policy.first_trading_day_after(publication_date)
    if effective_date is None:
        return _blocked_audit(
            policy=policy,
            observation=observation,
            code=TRADING_CALENDAR_UNAVAILABLE,
            message="trading calendar has no trading day after publish_date",
            field_name="trading_days",
            publish_date=publish_iso,
            announcement_timestamp=timestamp_display,
            provided_effective_date=provided_iso,
            timestamp_quality=timestamp_quality,
            session=session,
            effective_status=effective_status,
            return_status=return_status,
        )

    effective_iso = effective_date.isoformat()
    if not _is_missing(observation.provided_effective_date):
        try:
            provided_date = _parse_date(observation.provided_effective_date)
        except (TypeError, ValueError):
            return _blocked_audit(
                policy=policy,
                observation=observation,
                code=EFFECTIVE_DATE_POLICY_MISMATCH,
                message="provided_effective_date must be a valid calendar date",
                field_name="provided_effective_date",
                publish_date=publish_iso,
                announcement_timestamp=timestamp_display,
                provided_effective_date=provided_iso,
                timestamp_quality=timestamp_quality,
                session=session,
                effective_status="invalid",
                return_status=return_status,
                derived_effective_date=effective_iso,
            )
        provided_iso = provided_date.isoformat()
        if provided_date < publication_date:
            return _blocked_audit(
                policy=policy,
                observation=observation,
                code=EFFECTIVE_DATE_BEFORE_PUBLICATION,
                message="provided_effective_date is earlier than publish_date",
                field_name="provided_effective_date",
                publish_date=publish_iso,
                announcement_timestamp=timestamp_display,
                provided_effective_date=provided_iso,
                timestamp_quality=timestamp_quality,
                session=session,
                effective_status="invalid",
                return_status=return_status,
                derived_effective_date=effective_iso,
            )
        if provided_date != effective_date:
            return _blocked_audit(
                policy=policy,
                observation=observation,
                code=EFFECTIVE_DATE_POLICY_MISMATCH,
                message="provided_effective_date does not match the frozen timing policy",
                field_name="provided_effective_date",
                publish_date=publish_iso,
                announcement_timestamp=timestamp_display,
                provided_effective_date=provided_iso,
                timestamp_quality=timestamp_quality,
                session=session,
                effective_status="mismatch",
                return_status=return_status,
                derived_effective_date=effective_iso,
            )
        effective_status = "matched"
    else:
        provided_iso = None
        effective_status = "derived"

    if not _is_missing(observation.return_start_date):
        try:
            return_start = _parse_date(observation.return_start_date)
        except (TypeError, ValueError):
            return _blocked_audit(
                policy=policy,
                observation=observation,
                code=RETURN_START_BEFORE_EFFECTIVE_DATE,
                message="return_start_date must be a valid calendar date",
                field_name="return_start_date",
                publish_date=publish_iso,
                announcement_timestamp=timestamp_display,
                provided_effective_date=provided_iso,
                timestamp_quality=timestamp_quality,
                session=session,
                effective_status=effective_status,
                return_status="invalid",
                derived_effective_date=effective_iso,
            )
        if return_start < effective_date:
            return _blocked_audit(
                policy=policy,
                observation=observation,
                code=RETURN_START_BEFORE_EFFECTIVE_DATE,
                message="return_start_date is earlier than derived effective_date",
                field_name="return_start_date",
                publish_date=publish_iso,
                announcement_timestamp=timestamp_display,
                provided_effective_date=provided_iso,
                timestamp_quality=timestamp_quality,
                session=session,
                effective_status=effective_status,
                return_status="blocked",
                derived_effective_date=effective_iso,
            )
        return_status = "passed"

    return TimingAudit(
        code=code,
        statement_version=statement_version,
        source_record_id=source_record_id,
        timing_policy_version=policy.timing_policy_version,
        trading_calendar_version=policy.trading_calendar_version,
        timezone=policy.timezone,
        publish_date=publish_iso,
        announcement_timestamp=timestamp_display,
        timestamp_quality=timestamp_quality,
        market_session_classification=session,
        derived_effective_date=effective_iso,
        provided_effective_date=provided_iso,
        effective_date_validation_status=effective_status,
        decision_reason_code=_success_reason(session),
        return_start_validation_status=return_status,
        overall_status=TimingStatus.PASSED.value,
    )


def _blocked_audit(
    *,
    policy: FinancialTimingPolicy,
    observation: FinancialTimingObservation,
    code: str,
    message: str,
    field_name: str,
    publish_date: str | None,
    announcement_timestamp: str | None,
    provided_effective_date: str | None,
    timestamp_quality: str,
    session: str,
    effective_status: str,
    return_status: str,
    derived_effective_date: str | None = None,
) -> TimingAudit:
    return TimingAudit(
        code=_optional_text(observation.code),
        statement_version=_optional_text(observation.statement_version),
        source_record_id=_optional_text(observation.source_record_id),
        timing_policy_version=policy.timing_policy_version,
        trading_calendar_version=policy.trading_calendar_version,
        timezone=policy.timezone,
        publish_date=publish_date,
        announcement_timestamp=announcement_timestamp,
        timestamp_quality=timestamp_quality,
        market_session_classification=session,
        derived_effective_date=derived_effective_date,
        provided_effective_date=provided_effective_date,
        effective_date_validation_status=effective_status,
        decision_reason_code=code,
        return_start_validation_status=return_status,
        overall_status=TimingStatus.BLOCKED.value,
        errors=(TimingIssue(code=code, message=message, field_name=field_name),),
    )


def _parse_announcement_timestamp(
    value: Any,
    declared_timezone: Any,
    policy: FinancialTimingPolicy,
) -> datetime:
    if not isinstance(declared_timezone, str) or declared_timezone.strip() != policy.timezone:
        raise _TimingValidationError(
            ANNOUNCEMENT_TIMEZONE_UNVERIFIED,
            f"announcement_timezone must explicitly equal {policy.timezone}",
            "announcement_timezone",
        )

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        if len(raw) <= 10:
            raise _TimingValidationError(
                ANNOUNCEMENT_TIMESTAMP_INVALID,
                "announcement_timestamp must contain a time component",
                "announcement_timestamp",
            )
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _TimingValidationError(
                ANNOUNCEMENT_TIMESTAMP_INVALID,
                "announcement_timestamp must be valid ISO-8601",
                "announcement_timestamp",
            ) from exc
    else:
        raise _TimingValidationError(
            ANNOUNCEMENT_TIMESTAMP_INVALID,
            "announcement_timestamp must be datetime or ISO-8601 text",
            "announcement_timestamp",
        )

    zone = ZoneInfo(policy.timezone)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=zone)

    expected_offset = parsed.replace(tzinfo=None).replace(tzinfo=zone).utcoffset()
    if parsed.utcoffset() != expected_offset:
        raise _TimingValidationError(
            ANNOUNCEMENT_TIMEZONE_UNVERIFIED,
            "announcement_timestamp offset is inconsistent with Asia/Shanghai",
            "announcement_timestamp",
        )
    return parsed.astimezone(zone)


def _classify_market_session(
    announcement: datetime,
    publication_date: date,
    policy: FinancialTimingPolicy,
) -> str:
    if not policy.is_trading_day(publication_date):
        return MarketSessionClassification.NON_TRADING_DAY.value
    local_time = announcement.timetz().replace(tzinfo=None)
    if local_time < policy.market_open:
        return MarketSessionClassification.PRE_MARKET.value
    if local_time >= policy.market_close:
        return MarketSessionClassification.POST_MARKET.value
    return MarketSessionClassification.IN_SESSION.value


def _success_reason(session: str) -> str:
    return {
        MarketSessionClassification.DATE_ONLY.value:
            "CONSERVATIVE_NEXT_TRADING_DAY_DATE_ONLY",
        MarketSessionClassification.PRE_MARKET.value:
            "CONSERVATIVE_NEXT_TRADING_DAY_PRE_MARKET",
        MarketSessionClassification.IN_SESSION.value:
            "CONSERVATIVE_NEXT_TRADING_DAY_IN_SESSION",
        MarketSessionClassification.POST_MARKET.value:
            "CONSERVATIVE_NEXT_TRADING_DAY_POST_MARKET",
        MarketSessionClassification.NON_TRADING_DAY.value:
            "CONSERVATIVE_NEXT_TRADING_DAY_NON_TRADING_DAY",
    }.get(session, "CONSERVATIVE_NEXT_TRADING_DAY")


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise TypeError("date value must be non-empty text or date")
    return date.fromisoformat(value.strip())


def _display_date(value: Any) -> str | None:
    if _is_missing(value):
        return None
    try:
        return _parse_date(value).isoformat()
    except (TypeError, ValueError):
        return _display_value(value)


def _display_value(value: Any) -> str | None:
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
