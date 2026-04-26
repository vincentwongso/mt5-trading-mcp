"""PolicyEngine — single facade over preflight + consent + idempotency + audit.

Tools call `with engine.guard(action, request, requires_approval=..., ...)`
inside their body, after they've computed the gate logic. The engine
handles the retry mechanism: storing previews, validating retries, caching
idempotent results, and writing the audit trail.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from pydantic import BaseModel

from mt5_mcp.config import Config
from mt5_mcp.errors import idempotency_diverged_error, invalid_approval_error
from mt5_mcp.policy.audit import AuditLog
from mt5_mcp.policy.consent import ApprovalStore, new_request_id, validate_retry
from mt5_mcp.policy.idempotency import IdempotencyStore
from mt5_mcp.policy.preflight import PreflightInputs, check_preflight_limits
from mt5_mcp.types import ApprovalPreview, ErrorDetail, OrderResult


logger = logging.getLogger(__name__)


Action = Literal["place_order", "modify_order", "cancel_order", "close_position"]


@dataclass
class GuardedExecution:
    """Yielded by PolicyEngine.guard(); collaborates with the tool body."""

    action: Action
    request: BaseModel
    request_hash: str
    short_circuit: dict[str, Any] | None = None
    _finalized: bool = False
    _raw: Any = None
    _execute_duration_ms: int | None = None
    _engine: "PolicyEngine | None" = None

    def execute(self, callback: Callable[[], Any]) -> Any:
        t0 = time.perf_counter()
        try:
            self._raw = callback()
            return self._raw
        finally:
            self._execute_duration_ms = int((time.perf_counter() - t0) * 1000)

    def finalize(
        self,
        raw_to_result_fn: Callable[..., OrderResult],
        *,
        request_echo: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self._engine is None:
            raise RuntimeError("GuardedExecution.finalize called without engine binding")
        return self._engine._finalize(
            self, raw_to_result_fn, request_echo=request_echo, **kwargs
        )


class PolicyEngine:
    def __init__(
        self,
        *,
        config: Config,
        idempotency_path: Path | str,
        audit_path: Path | str,
    ) -> None:
        self._config = config
        self._idempotency = IdempotencyStore(
            path=idempotency_path,
            ttl_seconds=config.idempotency.ttl_seconds,
        )
        self._audit = AuditLog(path=audit_path, max_bytes=config.audit.max_bytes)
        self._approvals = ApprovalStore()

    @contextlib.contextmanager
    def guard(
        self,
        action: Action,
        request: BaseModel,
        *,
        requires_approval: bool,
        preview_factory: Callable[[], ApprovalPreview] | None = None,
        preflight_inputs: PreflightInputs | None = None,
        current_price: Decimal | None = None,
        symbol_point: Decimal | None = None,
    ) -> Iterator[GuardedExecution]:
        request_hash = self._hash_request(request)
        g = GuardedExecution(action=action, request=request,
                             request_hash=request_hash, _engine=self)

        # 1. Idempotency lookup.
        idem_key = getattr(request, "idempotency_key", None)
        idem = self._idempotency.lookup(
            key=idem_key, action=action, request_hash=request_hash
        )
        if idem is not None:
            kind, payload = idem
            if kind == "hit":
                cached = json.loads(payload)
                cached["replayed"] = True
                self._audit.write({"tool": action, "action": "replay",
                                   "idempotency_key": idem_key,
                                   "request_hash": request_hash})
                g.short_circuit = cached
                yield g
                return
            if kind == "diverged":
                err = idempotency_diverged_error(key=str(idem_key), action=action)
                self._audit.write({"tool": action, "action": "idempotency_diverged",
                                   "idempotency_key": idem_key,
                                   "request_hash": request_hash})
                g.short_circuit = {"error": err.model_dump(mode="json")}
                yield g
                return

        # Read approval state once for use across both consent branches.
        approval_confirmed = bool(getattr(request, "approval_confirmed", False))
        approval_request_id = getattr(request, "approval_request_id", None)

        # 3. Consent (confirmed retry) — runs BEFORE preflight so a
        # bait-and-switch surfaces as INVALID_APPROVAL rather than being
        # masked by EXCEEDS_LOCAL_LIMIT (architecture §8.1).
        if requires_approval and approval_confirmed:
            if not approval_request_id:
                err = ErrorDetail(
                    code="INVALID_APPROVAL",
                    message="approval_confirmed=true requires approval_request_id",
                    retryable=True, requires_human=True,
                    details={"reason": "missing approval_request_id"},
                )
                self._audit.write({"tool": action, "action": "invalid_approval",
                                   "request_hash": request_hash})
                g.short_circuit = {"error": err.model_dump(mode="json")}
                yield g
                return

            stored = self._approvals.pop(approval_request_id)
            if stored is None:
                err = invalid_approval_error(reason="unknown or expired approval_request_id")
                self._audit.write({"tool": action, "action": "invalid_approval",
                                   "request_id": approval_request_id,
                                   "request_hash": request_hash})
                g.short_circuit = {"error": err.model_dump(mode="json")}
                yield g
                return

            if current_price is None or symbol_point is None:
                raise RuntimeError(
                    "PolicyEngine.guard(): requires_approval=True with "
                    "approval_confirmed=True requires 'current_price' and "
                    "'symbol_point' kwargs. Pass the current ask/bid price "
                    "(quantised to symbol point) and symbol.point before "
                    "calling guard()."
                )
            err = validate_retry(request, preview=stored,
                                 current_price=current_price, point=symbol_point)
            if err is not None:
                self._audit.write({"tool": action, "action": "invalid_approval",
                                   "request_id": approval_request_id,
                                   "request_hash": request_hash,
                                   "reason": err.details.get("reason") if err.details else None})
                g.short_circuit = {"error": err.model_dump(mode="json")}
                yield g
                return
            # Approval matched — fall through to preflight then execute.

        # 4. Preflight checks.
        if preflight_inputs is not None:
            err = check_preflight_limits(action, request, preflight_inputs, self._config)
            if err is not None:
                self._audit.write({"tool": action, "action": "preflight_refused",
                                   "request_hash": request_hash,
                                   "limit_name": err.details.get("limit_name") if err.details else None})
                g.short_circuit = {"error": err.model_dump(mode="json")}
                yield g
                return

        # 5. Consent (first-pass preview generation) — only when approval is
        # required AND the agent has not yet supplied approval_confirmed=True.
        if requires_approval and not approval_confirmed:
            if preview_factory is None:
                raise RuntimeError(
                    "PolicyEngine.guard(): requires_approval=True with "
                    "approval_confirmed=False requires a preview_factory. "
                    "Pass a zero-arg callable that returns an ApprovalPreview "
                    "describing the request to the human."
                )
            preview = preview_factory()
            preview = preview.model_copy(update={"request_id": new_request_id()})
            self._approvals.put(preview)
            self._audit.write({"tool": action, "action": "requires_approval",
                               "request_id": preview.request_id,
                               "request_hash": request_hash})
            g.short_circuit = preview.model_dump(mode="json")
            yield g
            return

        # 6. Yield to the tool body for execute() + finalize().
        try:
            yield g
        except Exception as exc:
            if not g._finalized:
                self._audit.write({"tool": action, "action": "error",
                                   "request_hash": request_hash,
                                   "exception_type": type(exc).__name__})
            raise

    def close(self) -> None:
        self._idempotency.close()
        self._audit.close()

    def _finalize(
        self,
        g: GuardedExecution,
        raw_to_result_fn: Callable[..., OrderResult],
        *,
        request_echo: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        result = raw_to_result_fn(
            g._raw,
            request_echo=request_echo,
            **kwargs,
        )
        if not isinstance(result, OrderResult):
            raise TypeError("raw_to_result_fn must return an OrderResult")
        result_dict = result.model_dump(mode="json")
        self._audit.write({
            "tool": g.action, "action": "executed",
            "request_hash": g.request_hash,
            "ticket": result.ticket,
            "duration_ms": g._execute_duration_ms,
            "result_status": "filled" if result.success else "rejected",
        })
        idem_key = getattr(g.request, "idempotency_key", None)
        if idem_key:
            self._idempotency.put(
                key=idem_key, action=g.action,
                request_hash=g.request_hash,
                result_json=json.dumps(result_dict, separators=(",", ":")),
            )
        g._finalized = True
        return result_dict

    @staticmethod
    def _hash_request(request: BaseModel) -> str:
        """SHA256 over canonical JSON, excluding approval_* fields."""
        data = request.model_dump(mode="json",
                                  exclude={"approval_confirmed", "approval_request_id"})
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
