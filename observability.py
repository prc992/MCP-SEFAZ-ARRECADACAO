"""Instrumentação opt-in por requisição; não altera contratos nem cálculos.

ContextVar isola requisições concorrentes (inclusive tarefas em threads FastAPI).
No logs de etapas não são incluídos SQL, prompt, resposta ou linhas.
"""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Callable

_CONTEXT: ContextVar[tuple[str, str] | None] = ContextVar('faro_observability_context', default=None)
_LAST_ERROR: ContextVar[str | None] = ContextVar('faro_last_error_stage', default=None)

@contextmanager
def request_context(session_id: str, interaction_id: str):
    token = _CONTEXT.set((session_id, interaction_id))
    error_token = _LAST_ERROR.set(None)
    try:
        yield
    finally:
        _LAST_ERROR.reset(error_token)
        _CONTEXT.reset(token)

def last_error_stage() -> str | None:
    return _LAST_ERROR.get()

@contextmanager
def medir(stage: str, *, details: dict | Callable[[], dict] | None = None):
    """Sempre propaga exceções. Logging nunca deve mudar resultado da requisição.

    `details` com callable permite fornecer número de linhas após execução.
    """
    context = _CONTEXT.get()
    if context is None:
        yield
        return
    inicio = perf_counter()
    erro = None
    try:
        yield
    except BaseException as exc:
        erro = type(exc).__name__
        # Preserva a etapa mais específica se uma exceção atravessar wrappers externos.
        if _LAST_ERROR.get() is None:
            _LAST_ERROR.set(stage)
        raise
    finally:
        try:
            from interaction_logger import registrar_etapa
            info = details() if callable(details) else details
            registrar_etapa(session_id=context[0], interaction_id=context[1], stage=stage,
                            duration_ms=(perf_counter() - inicio) * 1000,
                            status='error' if erro else 'success', error_type=erro,
                            details=info if isinstance(info, dict) else None)
        except Exception:
            # Não deixar observabilidade interromper regras e respostas do Faro.
            import logging
            logging.getLogger(__name__).exception('Falha no mecanismo de observabilidade')

def evento(stage: str, *, status='success', details: dict | None = None, error_type=None):
    context = _CONTEXT.get()
    if context is None:
        return
    try:
        from interaction_logger import registrar_etapa
        registrar_etapa(session_id=context[0], interaction_id=context[1], stage=stage,
                        duration_ms=0, status=status, error_type=error_type, details=details)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Falha ao registrar evento')
